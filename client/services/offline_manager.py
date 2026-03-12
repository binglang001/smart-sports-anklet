# -*- coding: UTF-8 -*-
"""离线缓存与批量同步服务。"""

from datetime import datetime
import json
import os
import uuid

import requests

from utils.logger import get_logger

logger = get_logger('services.offline_manager')


class OfflineManager:
    """离线数据管理器。"""

    def __init__(self, server_url, cache_dir="/root/.smart-sports-belt"):
        self.server_url = server_url.rstrip('/')
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(self.cache_dir, "cache.json")
        self.pending_file = os.path.join(self.cache_dir, "pending.json")
        self.device_file = os.path.join(self.cache_dir, "device_id.json")

        self.is_online = False
        self.pending_data = []
        self.cache_data = {}

        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            pass

        self.device_id = self._get_or_create_device_id()
        self._load_cache()
        self._load_pending()

    def _atomic_save_json(self, file_path, data):
        temp_path = file_path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False)
        os.replace(temp_path, file_path)

    def _get_or_create_device_id(self):
        try:
            if os.path.exists(self.device_file):
                with open(self.device_file, 'r', encoding='utf-8') as file:
                    return file.read().strip()

            device_id = str(uuid.uuid4())
            with open(self.device_file, 'w', encoding='utf-8') as file:
                file.write(device_id)
            return device_id
        except Exception:
            return "unknown"

    def _load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as file:
                    self.cache_data = json.load(file)
        except Exception:
            self.cache_data = {}

    def _load_pending(self):
        try:
            if os.path.exists(self.pending_file):
                with open(self.pending_file, 'r', encoding='utf-8') as file:
                    self.pending_data = json.load(file) or []
        except Exception:
            self.pending_data = []

    def _save_cache(self):
        try:
            self._atomic_save_json(self.cache_file, self.cache_data)
        except Exception:
            pass

    def _save_pending(self):
        try:
            self._atomic_save_json(self.pending_file, self.pending_data)
        except Exception:
            pass

    def append_pending_record(self, record):
        """追加待同步记录。"""
        self.pending_data.append(record)
        self._save_pending()

    def update_cache(self, data):
        today = datetime.now().strftime("%Y-%m-%d")

        if today not in self.cache_data:
            self.cache_data[today] = {
                "steps": 0,
                "carbon": 0,
                "duration": 0,
                "last_update": None,
            }

        current_steps = data.get("step", 0)
        last_steps = self.cache_data[today].get("steps", 0)

        if current_steps >= last_steps:
            self.cache_data[today]["steps"] = current_steps
            self.cache_data[today]["carbon"] = data.get("carbon_reduce", 0)
            self.cache_data[today]["duration"] = data.get("sport_time_today", 0)
            self.cache_data[today]["last_update"] = datetime.now().isoformat()

        self._save_cache()

    def set_online_status(self, is_online):
        """设置在线状态。"""
        was_offline = not self.is_online
        self.is_online = is_online
        if was_offline and is_online:
            logger.info("已切换到在线模式")
        elif not was_offline and not is_online:
            logger.info("已切换到离线模式")

    def try_connect(self):
        """尝试连接服务器，返回是否成功。"""
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            session = requests.Session()
            retry = Retry(total=0, connect=0, read=0, redirect=0)
            adapter = HTTPAdapter(max_retries=retry)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            response = session.get(f"{self.server_url}/api/status", timeout=3)
            return response.status_code == 200
        except Exception:
            return False

    def sync_all_pending(self):
        """批量同步所有待上传记录。"""
        if not self.is_online or not self.pending_data:
            return 0

        try:
            response = requests.post(
                f"{self.server_url}/api/sync_records",
                json={"records": self.pending_data},
                timeout=10,
            )
            if response.status_code == 200:
                result = response.json()
                synced_count = result.get("synced_count", 0)
                self.pending_data = []
                self._save_pending()
                logger.info(f"批量同步成功: {synced_count} 条记录")
                return synced_count
        except Exception as e:
            logger.warning(f"批量同步失败: {e}")
        return 0
