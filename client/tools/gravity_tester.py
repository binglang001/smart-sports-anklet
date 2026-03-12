# -*- coding: UTF-8 -*-
"""
重力去除参数测试器

交互式测试不同参数下的重力去除效果
"""

import csv
import os
import sys
import math

from common import ensure_project_root

ensure_project_root()

# 导入日志模块
from utils.logger import get_logger
logger = get_logger('tools.gravity_tester')


class GravityTester:
    """重力去除参数测试器"""

    def __init__(self, csv_file, default_alpha=0.3, default_window=5):
        self.csv_file = csv_file
        self.raw_data = []
        self.current_alpha = default_alpha
        self.current_window = default_window

    def load_data(self):
        """加载CSV数据"""
        if not os.path.exists(self.csv_file):
            logger.error(f"文件不存在: {self.csv_file}")
            return False

        with open(self.csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.raw_data.append({
                    'acc_x': float(row['acc_x']),
                    'acc_y': float(row['acc_y']),
                    'acc_z': float(row['acc_z']),
                })

        logger.info(f"加载了 {len(self.raw_data)} 条数据")
        return True

    def process(self, alpha, window_size):
        """
        使用指定参数处理数据

        参数:
            alpha: 滤波系数 (0-1)
            window_size: 滑动平均窗口大小
        """
        if not self.raw_data:
            return []

        results = []

        # 重力加速度初始值
        gravity_x = 0.0
        gravity_y = 0.0
        gravity_z = 0.0
        is_first = True

        # 滑动平均缓冲区
        buffer_x = []
        buffer_y = []
        buffer_z = []

        for data in self.raw_data:
            acc_x = data['acc_x']
            acc_y = data['acc_y']
            acc_z = data['acc_z']

            if is_first:
                gravity_x = 0.0
                gravity_y = 0.0
                gravity_z = 0.0
                linear_x = acc_x
                linear_y = acc_y
                linear_z = acc_z
                is_first = False
            else:
                # 低通滤波
                gravity_x = alpha * acc_x + (1 - alpha) * gravity_x
                gravity_y = alpha * acc_y + (1 - alpha) * gravity_y
                gravity_z = alpha * acc_z + (1 - alpha) * gravity_z

                # 线性加速度
                linear_x = acc_x - gravity_x
                linear_y = acc_y - gravity_y
                linear_z = acc_z - gravity_z

            # 滑动平均滤波
            buffer_x.append(linear_x)
            buffer_y.append(linear_y)
            buffer_z.append(linear_z)

            if len(buffer_x) > window_size:
                buffer_x.pop(0)
                buffer_y.pop(0)
                buffer_z.pop(0)

            if len(buffer_x) >= window_size:
                linear_x = sum(buffer_x) / len(buffer_x)
                linear_y = sum(buffer_y) / len(buffer_y)
                linear_z = sum(buffer_z) / len(buffer_z)

            linear_mag = math.sqrt(linear_x**2 + linear_y**2 + linear_z**2)

            results.append({
                'linear_x': linear_x,
                'linear_y': linear_y,
                'linear_z': linear_z,
                'linear_mag': linear_mag,
                'gravity_x': gravity_x,
                'gravity_y': gravity_y,
                'gravity_z': gravity_z,
            })

        return results

    def analyze(self, results):
        """分析处理结果"""
        if not results:
            logger.info("无结果数据")
            return

        linear_mags = [r['linear_mag'] for r in results]
        linear_ys = [r['linear_y'] for r in results]

        avg_mag = sum(linear_mags) / len(linear_mags)
        max_mag = max(linear_mags)
        min_mag = min(linear_mags)

        avg_y = sum(linear_ys) / len(linear_ys)
        max_y = max(linear_ys)
        min_y = min(linear_ys)

        # 计算方差
        variance_mag = sum((x - avg_mag) ** 2 for x in linear_mags) / len(linear_mags)
        std_mag = math.sqrt(variance_mag)

        variance_y = sum((x - avg_y) ** 2 for x in linear_ys) / len(linear_ys)
        std_y = math.sqrt(variance_y)

        logger.info("\n" + "=" * 50)
        logger.info(f"参数: alpha={self.current_alpha}, window={self.current_window}")
        logger.info("=" * 50)
        logger.info(f"样本数: {len(results)}")
        logger.info(f"线性加速度幅值:")
        logger.info(f"  均值: {avg_mag:.4f}g")
        logger.info(f"  标准差: {std_mag:.4f}g")
        logger.info(f"  范围: [{min_mag:.4f}, {max_mag:.4f}]")
        logger.info(f"线性加速度Y轴:")
        logger.info(f"  均值: {avg_y:.4f}g")
        logger.info(f"  标准差: {std_y:.4f}g")
        logger.info(f"  范围: [{min_y:.4f}, {max_y:.4f}]")

    def run(self):
        """运行交互式测试"""
        logger.info("\n" + "=" * 60)
        logger.info("重力去除参数测试器")
        logger.info("=" * 60)
        logger.info("可用命令:")
        logger.info("  a <value>  - 设置滤波系数 alpha (0.0-1.0)")
        logger.info("  w <value>  - 设置滑动窗口大小 (1-20)")
        logger.info("  t          - 使用当前参数测试")
        logger.info("  q          - 退出")
        logger.info("=" * 60)

        while True:
            try:
                cmd = input("\n请输入命令: ").strip().lower()

                if cmd.startswith('a '):
                    # 设置alpha
                    try:
                        value = float(cmd[2:])
                        if 0 < value <= 1:
                            self.current_alpha = value
                            logger.info(f"滤波系数已设置为: {value}")
                        else:
                            logger.warning("alpha 必须在 0-1 之间")
                    except ValueError:
                        logger.error("无效的数值")

                elif cmd.startswith('w '):
                    # 设置窗口大小
                    try:
                        value = int(cmd[2:])
                        if 1 <= value <= 20:
                            self.current_window = value
                            logger.info(f"滑动窗口已设置为: {value}")
                        else:
                            logger.warning("窗口大小必须在 1-20 之间")
                    except ValueError:
                        logger.error("无效的数值")

                elif cmd == 't':
                    # 测试
                    results = self.process(self.current_alpha, self.current_window)
                    self.analyze(results)

                elif cmd == 'q':
                    # 退出
                    logger.info("退出测试器")
                    break

                else:
                    logger.info("未知命令，请重试")

            except KeyboardInterrupt:
                logger.info("\n退出测试器")
                break
            except Exception as e:
                logger.error(f"错误: {e}")


def main():
    import argparse

    # 从config读取默认参数
    try:
        import config
        default_alpha = config.GRAVITY_REMOVER_CONFIG.get("filter_alpha", 0.3)
        default_window = config.GRAVITY_REMOVER_CONFIG.get("filter_window", 5)
    except:
        default_alpha = 0.3
        default_window = 5

    parser = argparse.ArgumentParser(description='重力去除参数测试器')
    parser.add_argument('input', nargs='?', help='输入CSV文件')
    parser.add_argument('--alpha', type=float, default=default_alpha, help=f'滤波系数 (默认{default_alpha})')
    parser.add_argument('--window', type=int, default=default_window, help=f'滑动窗口大小 (默认{default_window})')
    parser.add_argument('--test', action='store_true', help='直接运行测试并退出')

    args = parser.parse_args()

    # 自动查找最新文件
    input_file = args.input
    if not input_file:
        data_dir = 'data/gravity'
        if os.path.exists(data_dir):
            csv_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
            if csv_files:
                csv_files.sort(key=lambda f: os.path.getmtime(os.path.join(data_dir, f)), reverse=True)
                input_file = os.path.join(data_dir, csv_files[0])

    if not input_file:
        logger.error("未找到数据文件，请先运行 gravity_collector.py 采集数据")
        sys.exit(1)

    logger.info(f"使用数据文件: {input_file}")

    tester = GravityTester(input_file, default_alpha, default_window)

    if not tester.load_data():
        sys.exit(1)

    tester.current_alpha = args.alpha
    tester.current_window = args.window

    if args.test:
        results = tester.process(args.alpha, args.window)
        tester.analyze(results)
    else:
        tester.run()


if __name__ == '__main__':
    main()
