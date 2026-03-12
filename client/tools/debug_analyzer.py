#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
调试数据分析器
用于分析步数检测、姿态检测和跌倒检测的调试数据

功能：
- 加载最新的调试数据
- 绘制单独的图表（每张图一个文件）
- 在步数检测位置做标记
- 支持中文字体
"""

import os
import sys
import csv
import argparse
from datetime import datetime
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# 导入日志模块
from common import ensure_project_root

ensure_project_root()
from utils.logger import get_logger
logger = get_logger('tools.debug_analyzer')

# 中文字体映射表
CHINESE_FONTS = [
    'SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC',
    'Source Han Sans CN', 'PingFang SC', 'STHeiti', 'Arial Unicode MS',
    'DejaVu Sans'
]

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    # 尝试设置中文字体
    font_found = False
    for font in CHINESE_FONTS:
        try:
            plt.rcParams['font.sans-serif'] = [font] + plt.rcParams.get('font.sans-serif', [])
            plt.rcParams['axes.unicode_minus'] = False
            # 测试字体是否可用
            plt.figure()
            plt.close()
            font_found = True
            break
        except:
            continue

    if not font_found:
        # 如果没有中文字体，使用英文标签
        logger.warning("未找到中文字体，图表将使用英文标签")

    PLOT_AVAILABLE = True
except ImportError:
    PLOT_AVAILABLE = False
    logger.warning("matplotlib未安装，将只输出文本分析")


class DebugAnalyzer:
    """调试数据分析器"""

    def __init__(self, debug_file):
        self.debug_file = debug_file
        self.records = []
        self.step_records = []
        self.posture_records = []
        self.fall_records = []

    def load_data(self):
        """加载调试数据"""
        if not os.path.exists(self.debug_file):
            logger.error(f"文件不存在: {self.debug_file}")
            return False

        with open(self.debug_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.records.append(row)
                record_type = row.get('type', '')

                if record_type == 'step':
                    self.step_records.append(row)
                elif record_type == 'posture':
                    self.posture_records.append(row)
                elif record_type == 'fall':
                    self.fall_records.append(row)

        logger.info(f"加载了 {len(self.records)} 条记录")
        logger.info(f"  - 步数记录: {len(self.step_records)}")
        logger.info(f"  - 姿态记录: {len(self.posture_records)}")
        logger.info(f"  - 跌倒记录: {len(self.fall_records)}")
        return True

    def analyze_steps(self):
        """分析步数检测"""
        logger.info("\n" + "=" * 60)
        logger.info("步数检测分析")
        logger.info("=" * 60)

        if not self.step_records:
            logger.info("无步数检测记录")
            return

        detected_steps = [r for r in self.step_records if r.get('step_detected') == 'True']
        total_steps = len(detected_steps)

        logger.info(f"总步数检测次数: {total_steps}")

        if total_steps > 0:
            logger.info("\n检测到的步数时间点:")
            for i, record in enumerate(detected_steps[:20]):
                timestamp = record.get('timestamp', '')
                acc_mag = float(record.get('acc_magnitude', 0))
                threshold = float(record.get('threshold', 0))
                logger.info(f"  {i+1}. {timestamp} - 加速度: {acc_mag:.3f}g, 阈值: {threshold:.3f}g")

            if total_steps > 20:
                logger.info(f"  ... 还有 {total_steps - 20} 次检测")

        thresholds = [float(r.get('threshold', 0)) for r in self.step_records if r.get('threshold')]
        if thresholds:
            logger.info(f"\n阈值统计:")
            logger.info(f"  平均阈值: {sum(thresholds)/len(thresholds):.4f}g")
            logger.info(f"  最小阈值: {min(thresholds):.4f}g")
            logger.info(f"  最大阈值: {max(thresholds):.4f}g")

    def analyze_posture(self):
        """分析姿态检测"""
        logger.info("\n" + "=" * 60)
        logger.info("姿态检测分析")
        logger.info("=" * 60)

        if not self.posture_records:
            logger.info("无姿态检测记录")
            return

        postures = defaultdict(int)
        motion_levels = []
        for record in self.posture_records:
            posture = record.get('posture', 'unknown')
            postures[posture] += 1
            # 收集运动水平
            try:
                ml = float(record.get('motion_level', 0))
                if ml > 0:
                    motion_levels.append(ml)
            except:
                pass

        logger.info("姿态分布:")
        for posture, count in sorted(postures.items()):
            percentage = count / len(self.posture_records) * 100
            logger.info(f"  {posture}: {count} 次 ({percentage:.1f}%)")

        # 姿态角统计
        pitch_values = []
        roll_values = []
        for record in self.posture_records:
            try:
                pitch = record.get('pitch', '0')
                roll = record.get('roll', '0')
                if pitch and pitch != '0':
                    pitch_values.append(float(pitch))
                if roll and roll != '0':
                    roll_values.append(float(roll))
            except (ValueError, TypeError):
                pass

        if pitch_values:
            logger.info(f"\n俯仰角(pitch)统计:")
            logger.info(f"  平均: {sum(pitch_values)/len(pitch_values):.2f} deg")
            logger.info(f"  范围: {min(pitch_values):.2f} ~ {max(pitch_values):.2f} deg")

        if roll_values:
            avg_roll = sum(roll_values)/len(roll_values)
            logger.info(f"\n翻滚角(roll)统计:")
            logger.info(f"  平均: {avg_roll:.2f} deg")
            logger.info(f"  范围: {min(roll_values):.2f} ~ {max(roll_values):.2f} deg")

            # 根据算法文档的姿态判断标准
            # 站立: roll -90 ~ -70, 坐姿: -70 ~ -30, 躺卧: -30 ~ +30
            standing = sum(1 for r in roll_values if -90 <= r <= -70)
            sitting = sum(1 for r in roll_values if -70 < r <= -30)
            lying = sum(1 for r in roll_values if -30 <= r <= 30)
            total = len(roll_values)

            if total > 0:
                logger.info(f"\n基于翻滚角的姿态分布(算法标准):")
                logger.info(f"  站立(-90~-70): {standing} ({standing/total*100:.1f}%)")
                logger.info(f"  坐姿(-70~-30): {sitting} ({sitting/total*100:.1f}%)")
                logger.info(f"  躺卧(-30~+30): {lying} ({lying/total*100:.1f}%)")

        # 运动水平统计
        if motion_levels:
            avg_motion = sum(motion_levels) / len(motion_levels)
            logger.info(f"\n运动水平统计:")
            logger.info(f"  平均: {avg_motion:.4f}")
            logger.info(f"  范围: {min(motion_levels):.4f} ~ {max(motion_levels):.4f}")

    def analyze_fall(self):
        """分析跌倒检测"""
        logger.info("\n" + "=" * 60)
        logger.info("跌倒检测分析")
        logger.info("=" * 60)

        if not self.fall_records:
            logger.info("无跌倒检测记录")
            return

        states = defaultdict(int)
        variances = []
        peak_accs = []
        angle_changes = []

        for record in self.fall_records:
            state = record.get('fall_state', 'unknown')
            states[state] += 1

            # 收集数值数据
            try:
                var = float(record.get('variance', 0))
                if var > 0:
                    variances.append(var)
            except:
                pass

            try:
                peak = float(record.get('peak_acc', 0))
                if peak > 0:
                    peak_accs.append(peak)
            except:
                pass

            try:
                angle = float(record.get('angle_change', 0))
                if angle != 0:
                    angle_changes.append(angle)
            except:
                pass

        logger.info("状态分布:")
        for state, count in sorted(states.items()):
            percentage = count / len(self.fall_records) * 100
            logger.info(f"  {state}: {count} 次 ({percentage:.1f}%)")

        # 加速度方差统计
        if variances:
            avg_var = sum(variances) / len(variances)
            logger.info(f"\n加速度方差统计:")
            logger.info(f"  平均: {avg_var:.4f}")
            logger.info(f"  最大: {max(variances):.4f}")
            logger.info(f"  最小: {min(variances):.4f}")

        # 峰值加速度统计
        if peak_accs:
            logger.info(f"\n峰值加速度统计:")
            logger.info(f"  平均: {sum(peak_accs)/len(peak_accs):.4f}g")
            logger.info(f"  最大: {max(peak_accs):.4f}g")

        # 角度变化统计
        if angle_changes:
            logger.info(f"\n角度变化统计:")
            logger.info(f"  平均: {sum(angle_changes)/len(angle_changes):.2f} deg")
            logger.info(f"  最大: {max(angle_changes):.2f} deg")

        # 跌倒状态分析
        # 根据算法文档: 疑似跌倒 -> 倾角计算 -> 确认跌倒
        confirmed_falls = states.get('confirmed', 0)
        impact_count = states.get('impact', 0)
        if confirmed_falls > 0 or impact_count > 0:
            logger.info(f"\n跌倒事件分析:")
            logger.info(f"  撞击检测: {impact_count} 次")
            logger.info(f"  确认跌倒: {confirmed_falls} 次")
        else:
            logger.info(f"\n状态: 未检测到跌倒事件")

    def plot_results(self, output_dir=None):
        """绘制可视化图表（每个图表单独一张图）"""
        if not PLOT_AVAILABLE:
            logger.info("\n跳过图表绘制 (matplotlib未安装)")
            return

        if not self.records:
            logger.info("\n跳过图表绘制 (无数据)")
            return

        if output_dir is None:
            output_dir = os.path.dirname(self.debug_file) or '.'

        # 准备数据
        timestamps = []
        acc_magnitudes = []
        pitches = []
        rolls = []
        step_detected = []
        postures = []
        fall_states = []
        thresholds = []

        # 分别存储不同类型的数据
        all_timestamps = []
        all_acc_mags = []
        all_step_detected = []

        # 用于姿态图的专用数据（只有姿态记录才有有效值）
        attitude_timestamps = []
        attitude_pitches = []
        attitude_rolls = []

        # 用于姿态检测图的专用数据
        posture_timestamps = []
        posture_accs = []
        posture_values = []

        # 用于跌倒图的专用数据
        fall_timestamps = []
        fall_accs = []
        fall_states_list = []

        # 用于步数检测图的专用数据（波峰时间点和加速度）
        step_peak_times = []
        step_peak_accs = []

        for record in self.records:
            try:
                ts = datetime.fromisoformat(record['timestamp'])
                acc_mag = float(record.get('acc_magnitude', 0))
                record_type = record.get('type', '')

                # 基础数据
                all_timestamps.append(ts)
                all_acc_mags.append(acc_mag)
                all_step_detected.append(record.get('step_detected', '0') == 'True')

                # 读取阈值（支持新旧格式）
                threshold_upper = float(record.get('threshold_upper', record.get('threshold', 0)))
                threshold_lower = float(record.get('threshold_lower', 0))
                thresholds.append(threshold_upper)

                # 步数检测时间点：优先使用 peak_time（波谷实际发生时间）
                if record_type == 'step' and record.get('step_detected', '0') == 'True':
                    peak_time_str = record.get('peak_time', '')
                    if peak_time_str:
                        try:
                            # peak_time 是时间戳，需要转换为 datetime
                            if isinstance(peak_time_str, (int, float)):
                                step_peak_times.append(datetime.fromtimestamp(peak_time_str))
                            else:
                                step_peak_times.append(datetime.fromisoformat(str(peak_time_str)))
                            step_peak_accs.append(acc_mag)
                        except (ValueError, TypeError):
                            # 回退到 record 的 timestamp
                            step_peak_times.append(ts)
                            step_peak_accs.append(acc_mag)
                    else:
                        step_peak_times.append(ts)
                        step_peak_accs.append(acc_mag)

                # 姿态数据（pitch/roll）
                pitch = record.get('pitch', '')
                roll = record.get('roll', '')
                if pitch and roll:
                    try:
                        attitude_timestamps.append(ts)
                        attitude_pitches.append(float(pitch))
                        attitude_rolls.append(float(roll))
                    except (ValueError, TypeError):
                        pass

                # 姿态检测数据
                posture = record.get('posture', '')
                if posture:
                    posture_timestamps.append(ts)
                    posture_accs.append(acc_mag)
                    posture_values.append(posture)

                # 跌倒检测数据
                fall_state = record.get('fall_state', '')
                if fall_state:
                    fall_timestamps.append(ts)
                    fall_accs.append(acc_mag)
                    fall_states_list.append(fall_state)

            except (ValueError, TypeError, KeyError):
                continue

        if not all_timestamps:
            logger.info("\n跳过图表绘制 (数据解析失败)")
            return

        timestamps = all_timestamps
        acc_magnitudes = all_acc_mags
        step_detected = all_step_detected

        # 获取检测到步数的时间点和阈值
        step_times = [timestamps[i] for i, v in enumerate(step_detected) if v]
        step_accs = [acc_magnitudes[i] for i, v in enumerate(step_detected) if v]

        # 创建阈值时间序列（只包含有阈值的点）
        step_threshold_times = []
        step_threshold_values = []
        # 确保thresholds和timestamps长度一致
        min_len = min(len(thresholds), len(timestamps))
        for i in range(min_len):
            try:
                if thresholds[i] > 0:
                    step_threshold_times.append(timestamps[i])
                    step_threshold_values.append(thresholds[i])
            except (IndexError, TypeError, ValueError):
                pass

        base_name = os.path.splitext(os.path.basename(self.debug_file))[0]

        # 图1：步数检测
        logger.info("\n生成图表 1: 步数检测...")
        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(timestamps, acc_magnitudes, 'b-', alpha=0.7, label='Acc Magnitude')
        if step_times:
            ax.scatter(step_times, step_accs, c='red', s=80, marker='^',
                      label=f'Steps Detected ({len(step_times)})', zorder=5)
        if step_threshold_times:
            ax.plot(step_threshold_times, step_threshold_values, 'g--', alpha=0.5, label='Threshold')
        ax.set_xlabel('Time')
        ax.set_ylabel('Acceleration (g)')
        ax.set_title(f'Step Detection - {base_name}')
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        output_file = os.path.join(output_dir, f'{base_name}_step_detection.png')
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        logger.info(f"  保存到: {output_file}")
        plt.close()

        # 图2：姿态角
        logger.info("生成图表 2: 姿态角...")
        if attitude_timestamps:
            fig, ax = plt.subplots(figsize=(14, 5))
            ax.plot(attitude_timestamps, attitude_pitches, 'b-', label='Pitch')
            ax.plot(attitude_timestamps, attitude_rolls, 'r-', label='Roll')
            ax.set_xlabel('Time')
            ax.set_ylabel('Angle (deg)')
            ax.set_title(f'Attitude Angles - {base_name}')
            ax.legend(loc='upper right')
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            output_file = os.path.join(output_dir, f'{base_name}_attitude.png')
            plt.savefig(output_file, dpi=150, bbox_inches='tight')
            logger.info(f"  保存到: {output_file}")
            plt.close()
        else:
            logger.info("  跳过: 无姿态数据")

        # 图3：姿态检测
        logger.info("生成图表 3: 姿态检测...")
        if posture_timestamps:
            fig, ax = plt.subplots(figsize=(14, 5))
            unique_postures = sorted(set(posture_values))
            posture_colors = {'standing': 'green', 'sitting': 'blue', 'moving': 'orange', 'unknown': 'gray'}
            for posture in unique_postures:
                indices = [i for i, p in enumerate(posture_values) if p == posture]
                times = [posture_timestamps[i] for i in indices]
                accs = [posture_accs[i] for i in indices]
                color = posture_colors.get(posture, 'gray')
                ax.scatter(times, accs, c=color, s=15, label=posture, alpha=0.6)
            ax.set_xlabel('Time')
            ax.set_ylabel('Acceleration (g)')
            ax.set_title(f'Posture Detection - {base_name}')
            ax.legend(loc='upper right')
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            output_file = os.path.join(output_dir, f'{base_name}_posture.png')
            plt.savefig(output_file, dpi=150, bbox_inches='tight')
            logger.info(f"  保存到: {output_file}")
            plt.close()
        else:
            logger.info("  跳过: 无姿态检测数据")

        # 图4：跌倒检测
        logger.info("生成图表 4: 跌倒检测...")
        if fall_timestamps:
            fig, ax = plt.subplots(figsize=(14, 5))
            unique_states = sorted(set(fall_states_list))
            state_colors = {'normal': 'green', 'warning': 'yellow', 'impact': 'orange',
                           'static': 'purple', 'confirmed': 'red', 'unknown': 'gray'}
            for state in unique_states:
                indices = [i for i, s in enumerate(fall_states_list) if s == state]
                times = [fall_timestamps[i] for i in indices]
                accs = [fall_accs[i] for i in indices]
                color = state_colors.get(state, 'gray')
                ax.scatter(times, accs, c=color, s=20, label=state, alpha=0.6)
            ax.set_xlabel('Time')
            ax.set_ylabel('Acceleration (g)')
            ax.set_title(f'Fall Detection - {base_name}')
            ax.legend(loc='upper right', ncol=3)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        output_file = os.path.join(output_dir, f'{base_name}_fall.png')
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        logger.info(f"  保存到: {output_file}")
        plt.close()

        # 图5：加速度时序详情（带步数标记）
        logger.info("生成图表 5: 加速度时序详情...")
        fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

        ax1 = axes[0]
        ax1.plot(timestamps, acc_magnitudes, 'b-', alpha=0.7, label='Acc Magnitude')
        if step_times:
            ax1.scatter(step_times, step_accs, c='red', s=80, marker='^',
                      label=f'Steps ({len(step_times)})', zorder=5)
        ax1.set_ylabel('Acceleration (g)')
        ax1.set_title(f'Acceleration Timeline with Step Markers - {base_name}')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        ax2 = axes[1]
        if attitude_timestamps:
            ax2.plot(attitude_timestamps, attitude_pitches, 'b-', label='Pitch')
            ax2.plot(attitude_timestamps, attitude_rolls, 'r-', label='Roll')
        ax2.set_xlabel('Time')
        ax2.set_ylabel('Angle (deg)')
        ax2.set_title('Attitude Angles')
        ax2.legend(loc='upper right')
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        output_file = os.path.join(output_dir, f'{base_name}_timeline.png')
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        logger.info(f"  保存到: {output_file}")
        plt.close()

        logger.info("\n所有图表生成完成!")

    def generate_tuning_suggestions(self):
        """生成调参建议"""
        logger.info("\n" + "=" * 60)
        logger.info("调参建议")
        logger.info("=" * 60)

        if not self.step_records:
            logger.info("无步数检测记录，无法生成建议")
            return

        # 收集数据
        motion_levels = []
        acc_mags = []
        detected_flags = []

        for record in self.step_records:
            try:
                ml = float(record.get('motion_level', 0))
                am = float(record.get('acc_magnitude', 0))
                df = record.get('step_detected', 'False') == 'True'
                if ml > 0:
                    motion_levels.append(ml)
                if am > 0:
                    acc_mags.append(am)
                detected_flags.append(df)
            except (ValueError, TypeError):
                pass

        if not motion_levels:
            logger.info("无有效运动数据，无法生成建议")
            return

        # 分析运动水平
        avg_motion = sum(motion_levels) / len(motion_levels)
        max_motion = max(motion_levels)
        min_motion = min(motion_levels)

        logger.info(f"\n运动水平分析:")
        logger.info(f"  平均: {avg_motion:.4f}")
        logger.info(f"  最大: {max_motion:.4f}")
        logger.info(f"  最小: {min_motion:.4f}")

        # 统计检测情况
        total_samples = len(detected_flags)
        detected_count = sum(detected_flags)
        detection_rate = detected_count / total_samples if total_samples > 0 else 0

        logger.info(f"\n检测情况:")
        logger.info(f"  总样本数: {total_samples}")
        logger.info(f"  检出次数: {detected_count}")
        logger.info(f"  检出率: {detection_rate:.2%}")

        # 生成建议
        logger.info("\n参数调整建议:")

        # 1. motion_threshold 分析
        logger.info("\n1. motion_threshold (运动检测阈值):")
        if avg_motion < 0.02 and detected_count > 0:
            logger.info("   ⚠ 当前阈值可能过高，建议降低到 0.02")
            logger.info("   原因: 平均运动水平很低但仍有检测，说明阈值过于敏感")
        elif avg_motion > 0.1 and detection_rate < 0.05:
            logger.info("   ⚠ 当前阈值可能过低，建议提高到 0.05")
            logger.info("   原因: 运动明显但检测率低，说明阈值过于严格")
        else:
            logger.info(f"   ✓ 当前值 ({self._get_current_threshold():.3f}) 合适")

        # 2. diff_threshold 分析
        logger.info("\n2. diff_threshold (差分阈值):")
        if detection_rate > 0.3:
            logger.info("   ⚠ 检出率过高，可能存在误检，建议提高阈值")
            logger.info("   建议: 将 diff_threshold 从 0.05 提高到 0.08-0.10")
        elif detection_rate < 0.01 and avg_motion > 0.03:
            logger.info("   ⚠ 检出率过低，可能漏检，建议降低阈值")
            logger.info("   建议: 将 diff_threshold 从 0.05 降低到 0.03")
        else:
            logger.info(f"   ✓ 当前值 ({self._get_current_threshold('diff'):.3f}) 合适")

        # 3. min_interval_ms 分析
        logger.info("\n3. min_interval_ms (最小步数间隔):")
        if detection_rate > 0.2:
            logger.info("   ⚠ 检出率过高，建议增大最小间隔")
            logger.info("   建议: 将 min_interval_ms 从 250 增加到 300-350")
        else:
            logger.info("   ✓ 当前值 (250ms) 合适")

        # 4. filter_window_size 分析
        logger.info("\n4. filter_window_size (滤波窗口大小):")
        if max_motion > 0.5:
            logger.info("   ⚠ 运动波动较大，建议增大滤波窗口")
            logger.info("   建议: 将 filter_window_size 从 5 增加到 7")
        elif min_motion < 0.01 and max_motion > 0.1:
            logger.info("   ✓ 当前滤波窗口适中")
        else:
            logger.info("   ✓ 当前值 (5) 合适")

        logger.info("\n" + "-" * 60)
        logger.info("快速调参指南:")
        logger.info("-" * 60)
        logger.info("""
参数影响对照表:
+------------------+--------------------+---------------------+
| 参数              | 调大               | 调小                |
+------------------+--------------------+---------------------+
| motion_threshold | 减少误检(更安静)   | 增加灵敏度(更敏感) |
| diff_threshold   | 减少误检(更严格)   | 增加灵敏度(更宽松)  |
| min_interval_ms  | 减少误检(间隔更大) | 增加步数(间隔更小)  |
| peak_threshold   | 减少误检(峰值更高) | 增加灵敏度(峰值更低)|
+------------------+--------------------+---------------------+
        """)

    def _get_current_threshold(self, threshold_type='motion'):
        """获取当前阈值配置(从配置文件或默认值)"""
        defaults = {
            'motion': 0.03,
            'diff': 0.05,
            'peak': 1.15,
            'min_interval': 250,
        }
        return defaults.get(threshold_type, 0.03)


def find_latest_debug_file(debug_dir='debug_data'):
    """查找最新的调试文件"""
    if not os.path.exists(debug_dir):
        return None

    csv_files = [f for f in os.listdir(debug_dir) if f.endswith('.csv')]
    if not csv_files:
        return None

    csv_files.sort(key=lambda f: os.path.getmtime(os.path.join(debug_dir, f)), reverse=True)
    return os.path.join(debug_dir, csv_files[0])


def main():
    parser = argparse.ArgumentParser(description='调试数据分析器')
    parser.add_argument('file', nargs='?', help='调试数据文件路径')
    parser.add_argument('--dir', default='debug_data', help='调试数据目录')
    parser.add_argument('--plot', action='store_true', help='生成可视化图表')
    parser.add_argument('--output', help='图表输出目录')
    parser.add_argument('--no-plot', action='store_true', help='不生成图表，只显示文本分析')

    args = parser.parse_args()

    debug_file = args.file
    if not debug_file:
        debug_file = find_latest_debug_file(args.dir)
        if not debug_file:
            logger.info(f"错误: 在 {args.dir} 中找不到调试文件")
            logger.info("Usage: python debug_analyzer.py <debug_file.csv>")
            sys.exit(1)

    logger.info(f"分析文件: {debug_file}")
    logger.info("-" * 60)

    analyzer = DebugAnalyzer(debug_file)

    if not analyzer.load_data():
        sys.exit(1)

    analyzer.analyze_steps()
    analyzer.analyze_posture()
    analyzer.analyze_fall()

    if not args.no_plot:
        analyzer.plot_results(args.output)

    # 自动生成调参建议
    analyzer.generate_tuning_suggestions()


if __name__ == "__main__":
    main()
