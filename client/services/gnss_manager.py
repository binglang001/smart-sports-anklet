# -*- coding: UTF-8 -*-
"""GNSS 管理服务。"""

from datetime import datetime
from glob import glob
import importlib
import math
import os
import sys

from utils.logger import get_logger

logger = get_logger('services.gnss_manager')

GNSS_AVAILABLE = False
GNSS_IMPORT_ERROR = None
GNSS_MODULE_PATH = None
GNSS_SEARCH_PATHS = []
DFRobot_GNSS_I2C = None
GPS_BeiDou_GLONASS = None


def _build_gnss_search_paths():
    """构建 GNSS 驱动可能存在的搜索路径。"""
    candidates = []

    env_path = os.environ.get('GNSS_LIB_PATH')
    if env_path:
        candidates.append(env_path)

    candidates.extend([
        "/root/mindplus/.lib/thirdExtension/liliang-gravitygnss-thirdex",
        "/root/mindplus/.lib/thirdExtension/gravitygnss-thirdex",
        "/root/mindplus/.lib/thirdExtension/DFRobot_GNSS-thirdex",
        "/root/mindplus/.lib/thirdExtension/dfrobot_gnss-thirdex",
    ])

    candidates.extend(sorted(glob("/root/mindplus/.lib/thirdExtension/*gnss*")))

    unique_paths = []
    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    return unique_paths


def _bootstrap_gnss_driver():
    """尝试导入 GNSS 驱动，并记录详细诊断信息。"""
    global GNSS_AVAILABLE, GNSS_IMPORT_ERROR, GNSS_MODULE_PATH, GNSS_SEARCH_PATHS
    global DFRobot_GNSS_I2C, GPS_BeiDou_GLONASS

    GNSS_SEARCH_PATHS = _build_gnss_search_paths()
    existing_paths = []
    for path in GNSS_SEARCH_PATHS:
        if os.path.isdir(path):
            existing_paths.append(path)
            if path not in sys.path:
                sys.path.append(path)

    try:
        gnss_module = importlib.import_module('DFRobot_GNSS')
        DFRobot_GNSS_I2C = getattr(gnss_module, 'DFRobot_GNSS_I2C', None)
        GPS_BeiDou_GLONASS = getattr(gnss_module, 'GPS_BeiDou_GLONASS', None)

        if DFRobot_GNSS_I2C is None or GPS_BeiDou_GLONASS is None:
            missing = []
            if DFRobot_GNSS_I2C is None:
                missing.append('DFRobot_GNSS_I2C')
            if GPS_BeiDou_GLONASS is None:
                missing.append('GPS_BeiDou_GLONASS')
            GNSS_IMPORT_ERROR = f"驱动已导入，但缺少符号: {missing}"
            logger.warning(GNSS_IMPORT_ERROR)
            return

        GNSS_AVAILABLE = True
        GNSS_IMPORT_ERROR = None
        GNSS_MODULE_PATH = getattr(gnss_module, '__file__', None) or next((path for path in existing_paths if path in sys.path), 'python-path')
        logger.info(f"GNSS驱动导入成功: {GNSS_MODULE_PATH}")
        return
    except Exception as exc:
        GNSS_IMPORT_ERROR = str(exc)
        searched = existing_paths if existing_paths else GNSS_SEARCH_PATHS
        logger.warning(f"GNSS模块不可用，驱动导入失败: {exc}；已检查路径: {searched}")


_bootstrap_gnss_driver()


class GNSSManager:
    """GNSS 管理器。"""

    def __init__(self, cfg=None):
        default_cfg = {
            "enabled": True,
            "min_satellites": 5,
            "speed_unit": "knot",
            "track_interval": 1.0,
            "min_move_distance_m": 0.8,
            "max_jump_distance_m": 35.0,
            "max_jump_speed_kmh": 25.0,
        }
        if cfg:
            default_cfg.update(cfg)
        self.config = default_cfg

        self.gnss = None
        self.is_active = False
        self.last_satellite_count = 0
        self._unavailable_logged = False
        self._disabled_logged = False

    def initialize(self):
        if not GNSS_AVAILABLE or not self.config["enabled"]:
            return False

        try:
            self.gnss = DFRobot_GNSS_I2C(bus=0, addr=0x20)

            if self.gnss.begin() is False:
                logger.error("GNSS初始化失败")
                self.gnss = None
                return False

            self.gnss.enable_power()
            self.gnss.set_gnss(GPS_BeiDou_GLONASS)
            rgb_on = getattr(self.gnss, 'rgb_on', None)
            if callable(rgb_on):
                rgb_on()
            logger.info("GNSS模块初始化成功")
            return True
        except Exception as exc:
            logger.warning(f"GNSS初始化异常: {exc}")
            self.gnss = None
            return False

    def start(self):
        """启动 GNSS。"""
        if not self.config["enabled"]:
            if not self._disabled_logged:
                logger.info("GNSS已在配置中禁用")
                self._disabled_logged = True
            return False

        if not GNSS_AVAILABLE:
            _bootstrap_gnss_driver()

        if not GNSS_AVAILABLE:
            if not self._unavailable_logged:
                detail = GNSS_IMPORT_ERROR or '未知导入错误'
                logger.warning(f"GNSS无法启动：驱动未导入成功，原因: {detail}")
                self._unavailable_logged = True
            return False

        self._unavailable_logged = False

        if self.is_active and self.gnss is not None:
            return True

        self.is_active = True
        if not self.initialize():
            self.is_active = False
            return False

        logger.info("GNSS已启动")
        return True

    def stop(self):
        """停止 GNSS。"""
        self.is_active = False
        self.last_satellite_count = 0
        if self.gnss:
            try:
                self.gnss.disable_power()
            except Exception:
                pass
        self.gnss = None

    def _call_numeric(self, *method_names):
        """按顺序调用 GNSS 数值接口，返回 float 或 None。"""
        if not self.is_active or not self.gnss:
            return None

        for method_name in method_names:
            method = getattr(self.gnss, method_name, None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception:
                continue
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _extract_attr(data, *names):
        """兼容对象属性和字典字段读取。"""
        if data is None:
            return None
        if isinstance(data, dict):
            for name in names:
                value = data.get(name)
                if value is not None:
                    return value
        for name in names:
            value = getattr(data, name, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_signed_degree(value, direction=None):
        """根据方向字段将经纬度转为带符号的十进制度。"""
        try:
            degree = float(value)
        except (TypeError, ValueError):
            return None

        direction = str(direction or '').upper()
        if direction in ('S', 'W'):
            degree = -abs(degree)
        elif direction in ('N', 'E'):
            degree = abs(degree)
        return degree

    @staticmethod
    def _is_valid_position(lat, lon):
        """校验经纬度是否像一个真实定位结果。"""
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            return False

        if abs(lat) > 90 or abs(lon) > 180:
            return False
        if abs(lat) < 1e-7 and abs(lon) < 1e-7:
            return False
        return True

    @staticmethod
    def haversine_distance_km(lat1, lon1, lat2, lon2):
        """计算两经纬度点之间的大圆距离，单位 km。"""
        try:
            lat1 = float(lat1)
            lon1 = float(lon1)
            lat2 = float(lat2)
            lon2 = float(lon2)
        except (TypeError, ValueError):
            return 0.0

        radius_km = 6371.0
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        delta_lat = lat2_rad - lat1_rad
        delta_lon = lon2_rad - lon1_rad
        a = math.sin(delta_lat / 2.0) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return radius_km * c

    def get_speed(self):
        """获取速度(km/h)，无效返回 None。"""
        speed = self._call_numeric('get_sog', 'get_speed')
        if speed is None or speed < 0:
            return None

        speed_unit = str(self.config.get('speed_unit', 'knot') or 'knot').strip().lower()
        if speed_unit in ('knot', 'knots', 'kt', 'kts', 'kn'):
            speed *= 1.852
        elif speed_unit in ('m/s', 'mps', 'meter_per_second', 'meters_per_second'):
            speed *= 3.6

        return speed

    def get_course(self):
        """获取航向角(度)，无效返回 None。"""
        course = self._call_numeric('get_cog', 'get_course')
        if course is None:
            return None
        return course % 360.0

    def get_position(self):
        """获取当前位置，返回 {lat, lon} 或 None。"""
        if not self.is_active or not self.gnss:
            return None

        try:
            lat_data = self.gnss.get_lat()
            lon_data = self.gnss.get_lon()
        except Exception:
            return None

        lat = self._to_signed_degree(
            self._extract_attr(lat_data, 'latitude_degree', 'latitude'),
            self._extract_attr(lat_data, 'lat_direction', 'latitude_direction'),
        )
        lon = self._to_signed_degree(
            self._extract_attr(lon_data, 'longitude_degree', 'lonitude_degree', 'longitude', 'lon'),
            self._extract_attr(lon_data, 'lon_direction', 'longitude_direction'),
        )

        if lat is None or lon is None:
            return None
        if not self._is_valid_position(lat, lon):
            return None

        return {
            'lat': round(lat, 7),
            'lon': round(lon, 7),
        }

    def get_track_point(self, sat_count=None):
        """获取轨迹点数据，便于运动记录直接落库。"""
        if not self.is_active or not self.gnss:
            return None

        if sat_count is not None and not self.is_fix_satellite_count(sat_count):
            return None

        position = self.get_position()
        if not position:
            return None

        if sat_count is None:
            sat_count = self.get_satellite_count()

        point = {
            'lat': position['lat'],
            'lon': position['lon'],
            'satellites': int(sat_count or 0),
        }

        speed = self.get_speed()
        if speed is not None:
            point['speed_kmh'] = round(speed, 2)

        course = self.get_course()
        if course is not None:
            point['heading_deg'] = round(course, 1)

        gnss_dt = self.get_datetime()
        if gnss_dt:
            point['utc'] = gnss_dt.strftime('%Y-%m-%dT%H:%M:%S')

        return point

    def get_satellite_count(self):
        """获取当前使用卫星数。"""
        if not self.is_active or not self.gnss:
            self.last_satellite_count = 0
            return 0

        try:
            num = self.gnss.get_num_sta_used()
            self.last_satellite_count = max(0, int(num)) if num is not None else 0
        except Exception:
            self.last_satellite_count = 0
        return self.last_satellite_count

    def is_fix_satellite_count(self, sat_count):
        """根据卫星数判断定位是否可用。"""
        return int(sat_count or 0) >= int(self.config.get('min_satellites', 5))

    def has_fix(self):
        """是否达到可用卫星数阈值。"""
        return self.is_fix_satellite_count(self.get_satellite_count())

    def has_valid_fix(self, sat_count=None):
        """是否同时满足卫星数和坐标有效。"""
        if sat_count is None:
            sat_count = self.get_satellite_count()
        if not self.is_fix_satellite_count(sat_count):
            return False
        return self.get_position() is not None

    def get_status_text(self, sat_count=None):
        """获取简短 GNSS 状态文本。"""
        if not GNSS_AVAILABLE or not self.config.get('enabled', True):
            return 'GPS:--'

        if sat_count is None:
            sat_count = self.get_satellite_count()

        if sat_count > 0:
            return f'GPS:{sat_count}'

        if self.is_active:
            return 'GPS:搜星'
        return 'GPS:关'

    def get_datetime(self):
        """获取 GNSS 时间，返回 datetime 或 None。"""
        if not self.is_active or not self.gnss:
            return None

        try:
            gnss_utc = self.gnss.get_date()
            gnss_time = self.gnss.get_utc()
            if gnss_utc and gnss_time:
                return datetime(
                    gnss_utc.year, gnss_utc.month, gnss_utc.date,
                    gnss_time.hour, gnss_time.minute, gnss_time.second
                )
        except Exception:
            pass
        return None
