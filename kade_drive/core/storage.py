import os
import pickle
from datetime import datetime

# from time import sleep
from pathlib import Path

# import threading
import base64
import logging


# Create a file handler
# file_handler = logging.FileHandler("log_file.log")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
# file_handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
# logger.addHandler(file_handler)


class PersistentStorage:
    """
    This class allows to persist files on disk using mongodb.
    The class acts as an OrderedDict that his keys are the hash of an
    specific file chunk and the value is the (ip, port) of the node that
    has the chunk in his mongodb instance. In the current implementation
    the values of the dict are not used. The get method directly access to
    mongodb and retrieve the data that correspond to the given dict
    """

    def __init__(self, ttl=120):
        """
        By default, max age is a week.
        """
        self.db_path = "static"
        self.values_path = "static/values"
        self.metadata_path = "static/metadata"
        self.keys_path = "static/keys"
        self.timestamp_path = "timestamps"
        self.db = []
        self.ttl = ttl
        self.is_deleting = False
        # self.stop_del_thread = False

        # self.del_thread = threading.Thread(target=self.delete_old)
        # self.del_thread.start()

        self.ensure_dir_paths()

    # def stop_thread(self):
    #     self.stop_del_thread = True
    #     self.del_thread.join()

    def ensure_dir_paths(self):
        os.makedirs(self.db_path, exist_ok=True)

        os.makedirs(self.values_path, exist_ok=True)

        os.makedirs(self.metadata_path, exist_ok=True)

        os.makedirs(self.keys_path, exist_ok=True)

        os.makedirs(self.timestamp_path, exist_ok=True)

    def update_timestamp(self, filename: str, republish_data=False, is_write=False):
        self.ensure_dir_paths()
        data = {}
        if os.path.exists(os.path.join(self.timestamp_path, str(filename))):
            with open(os.path.join(self.timestamp_path, str(filename)), "rb") as f:
                data = pickle.load(f)

        data["date"] = datetime.now()
        data["republish"] = republish_data

        if is_write:
            data["last_write"] = datetime.now()

        logger.debug(f"mira ruta {os.path.join(self.timestamp_path, str(filename))}")
        with open(os.path.join(self.timestamp_path, str(filename)), "wb") as f:
            pickle.dump(data, f)

    def update_republish(self, key: bytes):
        str_key = str(base64.urlsafe_b64encode(key))
        with open(os.path.join(self.timestamp_path, str_key), "rb") as f:
            data = pickle.load(f)
        with open(os.path.join(self.timestamp_path, str_key), "wb") as f:
            data["republish"] = False
            pickle.dump(data, f)

    def delete(self, key: bytes, is_metadata: bool) -> bool:
        try:
            str_key = str(base64.urlsafe_b64encode(key))
            self._delete_data(str_key, is_metadata)
            return True
        except Exception as e:
            logger.error(f"error when running delete {e}")
            return False

    def _delete_data(self, str_key: str, is_metadata: bool):
        key_path = Path(os.path.join(self.keys_path, str_key))
        if is_metadata:
            value_path = Path(os.path.join(self.metadata_path), str_key)
            if value_path.exists():
                with open(value_path, "wb") as f:
                    chunks_data = pickle.load(f)
                    chunks_data["integrity"] = False
                    pickle.dump(chunks_data, f)
                    chunks_value = chunks_data["value"]
                for v in chunks_value:
                    self._delete_data(v, False)

        else:
            value_path = Path(os.path.join(self.values_path), str_key)
        timestamp_path = Path(os.path.join(self.timestamp_path, str_key))
        if key_path.exists():
            os.remove(value_path)
        if value_path.exists():
            os.remove(value_path)
        if timestamp_path.exists():
            os.remove(timestamp_path)

    def delete_corrupted_data(self):
        self.is_deleting = True
        self.ensure_dir_paths()

        # while True:
        logger.debug("checking corrupted data")

        # if self.stop_del_thread:
        #     return
        for path, dir, files in os.walk(self.keys_path):
            for file in files:
                file_key_path = Path(os.path.join(self.keys_path), str(file))
                if file_key_path.exists():
                    try:
                        value = pickle.loads(self.get_value(str(file), metadata=False))
                        is_metadata = False
                    except FileNotFoundError:
                        value = pickle.loads(self.get_value(str(file), metadata=True))
                        is_metadata = True
                    if (
                        not value["integrity"]
                        and (datetime.now() - value["integrity_date"]).seconds
                        > self.ttl
                    ):
                        logger.info(
                            f"Removing file {file}, beacuse it has not been checked his integrity in {self.ttl/60} minutes"
                        )

                        self._delete_data(str(file), is_metadata=is_metadata)

            self.is_deleting = False
            # sleep(self.ttl)

    def get_value(self, str_key: str, update_timestamp=True, metadata=True):
        self.ensure_dir_paths()
        if metadata:
            path = os.path.join(self.metadata_path, str_key)
        else:
            path = os.path.join(self.values_path, str_key)

        result = None
        if os.path.exists(path):
            with open(path, "rb") as f:
                result = f.read()

        if result is not None:
            data = pickle.loads(result)
            if not data["integrity"]:
                return None
            if update_timestamp:
                self.update_timestamp(str_key, republish_data=True)
        if not result:
            logger.warning(f"tried to get non existing data with key {str_key}")

        return result

    def set_value(self, key: bytes, value, metadata=True, republish_data=False):
        str_key = str(base64.urlsafe_b64encode(key))
        self.ensure_dir_paths()
        self.update_timestamp(str_key, republish_data, is_write=True)
        value_to_set = pickle.dumps(
            {"integrity": False, "value": value, "integrity_date": datetime.now()}
        )

        if metadata:
            path = os.path.join(self.metadata_path, str_key)
        else:
            path = os.path.join(self.values_path, str_key)
        with open(path, "wb") as f:
            # try
            logger.debug("writting data  to file")
            f.write(value_to_set)
            # except TypeError:
            #     logger.warning("writting with unicode_escape")
            #     f.write(value_to_set.encode("unicode_escape"))

        with open(os.path.join(self.keys_path, str_key), "wb") as f:
            f.write(key)

    # def delete_value(self, key: bytes):
    #     str_key = str(base64.urlsafe_b64encode(key))
    #     self.ensure_dir_paths()
    #     self.delete_timestamp(str_key, republish_data, is_write=True)

    #     path = os.path.join(self.metadata_path, str_key)

    #     if os.path.exists(path):
    #         os.remove(path)
    #     path = os.path.join(self.values_path, str_key)

    #     if os.path.exists(path):
    #         os.remove(path)

    #     key_path = os.path.join(self.keys_path, str_key)

    #     if os.path.exists(key_path):
    #         os.remove(key_path)

    def confirm_integrity(self, key: bytes, metadata=True):
        str_key = str(base64.urlsafe_b64encode(key))
        self.ensure_dir_paths()
        if metadata:
            path = Path(os.path.join(self.metadata_path, str_key))
        else:
            path = Path(os.path.join(self.values_path, str_key))

        if path.exists():
            with open(path, "rb") as f:
                value = pickle.load(f)
            with open(path, "wb") as f:
                value["integrity"] = True
                f.write(pickle.dumps(value))
        else:
            logger.info("Tried to confirm integrity of non existing file")

    def set_metadata(self, key, value, republish_data: bool):
        self.ensure_dir_paths()
        self.set_value(key, value, True, republish_data)
        self.cull()

    # def delete_metadata(self, key):
    #     self.ensure_dir_paths()
    #     self.delete_value(key, True, )
    #     self.cull()

    def cull(self):
        """
        Check if there exist data older that {self.ttl} and remove it.
        """

    def get(self, key: bytes, default=None, update_timestamp=True, metadata=True):
        str_key = str(base64.urlsafe_b64encode(key))
        result = self.get_value(
            str_key, update_timestamp=update_timestamp, metadata=metadata
        )
        return result

    def get_key_in_bytes(self, key: str):
        path = Path(os.path.join(self.keys_path, key))
        if not path.exists():
            return None

        with open(os.path.join(self.keys_path, key), "rb") as f:
            result = f.read()
            return result, os.path.exists(os.path.join(self.metadata_path, key))

    def contains(self, key: bytes, is_metadata=True):
        str_key = str(base64.urlsafe_b64encode(key))
        logger.debug(f"str_key in contains is {str_key}")
        self.cull()
        if is_metadata:
            path = Path(os.path.join(self.metadata_path, str_key))
            if not path.exists():
                return False
        else:
            path = Path(os.path.join(self.values_path, str_key))
            if not path.exists():
                return False
        with open(path, "rb") as f:
            data = pickle.load(f)
            if not data["integrity"]:
                return False

        return True

    def check_if_new_value_exists(self, key):
        str_key = str(base64.urlsafe_b64encode(key))
        path = Path(os.path.join(self.timestamp_path, str_key))
        if not path.exists():
            return False, None

        with open(os.path.join(self.timestamp_path, str_key), "rb") as f:
            data = pickle.load(f)

        return True, data["last_write"]

    def __getitem__(self, key: bytes):
        self.cull()
        str_key = str(base64.urlsafe_b64encode(key))
        result = self.get_value(str_key)
        if result is None:
            raise KeyError()
        return result

    def __repr__(self):
        self.cull()

    def iter_older_than(self, seconds_old):
        self.ensure_dir_paths()
        for path, dir, files in os.walk(self.timestamp_path):
            for file in files:
                if Path(os.path.join(self.timestamp_path, file)).exists():
                    with open(os.path.join(self.timestamp_path, file), "rb") as f:
                        data = pickle.load(f)
                    if (datetime.now() - data["date"]).seconds >= seconds_old or data[
                        "republish"
                    ]:
                        key, is_metadata = self.get_key_in_bytes(str(file))
                        value = self.get_value(
                            str(file), update_timestamp=False, metadata=is_metadata
                        )
                        assert value is not None
                        yield key, value, is_metadata, data["last_write"]

    def keys(self):
        ikeys_files = os.listdir(os.path.join(self.keys_path))
        ikeys = []
        imetadata = []
        for key_name in ikeys_files:
            k, m = self.get_key_in_bytes(key_name)
            ikeys.append(k)
            imetadata.append(m)
        return zip(ikeys, imetadata)

    def __iter__(self):
        self.ensure_dir_paths()

        logger.debug("calling iter")
        ikeys_files = os.listdir(os.path.join(self.keys_path))
        ikeys: list[bytes] = []
        imetadata: list[bool] = []
        for key_name in ikeys_files:
            k, m = self.get_key_in_bytes(key_name)
            ikeys.append(k)
            imetadata.append(m)

        logger.debug("ikeys: %s", ikeys)
        ivalues: list[bytes] = []

        for i, ik in enumerate(ikeys):
            ivalues.append(self.get(ik, update_timestamp=False, metadata=imetadata[i]))
        return zip(ikeys, ivalues, imetadata)
