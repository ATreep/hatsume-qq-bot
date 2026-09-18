#!/usr/bin/env python3
"""
群成员发言统计 + 抽奖脚本
==========================
功能：统计指定群在最近 N 小时内发言 >= min_msgs 条的成员，从中随机抽取 top 位幸运用户。

数据来源：/work/hatsume/data/hatsume-plugin/message-db/message.db (SQLite)
消息表 messages: id, group_id, role, sender_qq_id, sender_name, content,
                 reply_to_message_id, platform_message_id, created_at, inserted_at

用法示例：
    python3 lucky_draw.py --hours 24 --min-msgs 4 --top 3
    python3 lucky_draw.py --hours 12 --min-msgs 5 --top 1 --group 738458661
    python3 lucky_draw.py --start-time 1789410240.0 --end-time 1789496640.0 --min-msgs 4 --top 3
    python3 lucky_draw.py --help
"""

import argparse
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone, timedelta


# ============ 配置区 ============
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "hatsume-plugin", "message-db", "message.db"
)
BOT_QQ_ID = 2502815560          # bot 自身的 QQ 号（排除）
DEFAULT_GROUP_ID = 738458661    # 「笨蛋小小」群的群号
TIMEZONE_CN = timezone(timedelta(hours=8))   # Asia/Shanghai


def parse_args():
    parser = argparse.ArgumentParser(
        description="群成员发言统计 + 幸运抽奖",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  %(prog)s --hours 24 --min-msgs 4 --top 3
  %(prog)s --hours 12 --min-msgs 5 --top 1 --group 738458661
  %(prog)s --start-time 1789410240.0 --end-time 1789496640.0 --min-msgs 4 --top 3
""",
    )
    parser.add_argument("--db", default=DB_PATH, help="消息数据库路径")
    parser.add_argument("--group", type=int, default=DEFAULT_GROUP_ID,
                        help=f"目标群号（默认 {DEFAULT_GROUP_ID}）")
    parser.add_argument("--hours", type=float, default=None,
                        help="回溯时长（小时，默认 None 则需用 --start-time/--end-time）")
    parser.add_argument("--min-msgs", type=int, default=4,
                        help="最小发言条数阈值（默认 4，即 > 3 条）")
    parser.add_argument("--top", type=int, default=3,
                        help="抽取幸运用户人数（默认 3）")
    parser.add_argument("--seed", type=int, default=None,
                        help="随机种子（不传则使用当前时间戳）")
    parser.add_argument("--bot-qq", type=int, default=BOT_QQ_ID,
                        help="需排除的 bot QQ 号")
    parser.add_argument("--start-time", type=float, default=None,
                        help="起始 Unix 时间戳（Asia/Shanghai 对应时间由脚本转换展示）")
    parser.add_argument("--end-time", type=float, default=None,
                        help="结束 Unix 时间戳（Asia/Shanghai 对应时间由脚本转换展示）")
    return parser.parse_args()


def query_messages(db_path, group_id, start_ts, end_ts, bot_qq):
    """查询指定窗口内的合格成员（user角色，非bot），返回排序后的列表。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    sql = """
        SELECT sender_qq_id, sender_name, COUNT(*) AS msg_count
        FROM messages
        WHERE group_id      = ?
          AND role          = 'user'
          AND created_at    >= ?
          AND created_at    <= ?
          AND sender_qq_id  != ?
        GROUP BY sender_qq_id, sender_name
        ORDER BY msg_count DESC, sender_qq_id ASC
    """
    cur.execute(sql, (group_id, start_ts, end_ts, bot_qq))
    rows = cur.fetchall()
    conn.close()
    return rows


def print_ranking(rows, min_msgs):
    """打印完整排行榜。"""
    qualified = [r for r in rows if r[2] >= min_msgs]
    disqual = [r for r in rows if r[2] < min_msgs]

    print("=" * 65)
    print(f"  合格成员排行榜  (发言 >= {min_msgs} 条) — 共 {len(qualified)} 人达标 / {len(disqual)} 人未达标")
    print("=" * 65)

    # 先打印合格的
    if qualified:
        print(f"\n[达标成员 ({len(qualified)} 人) —— 参与抽奖]")
        print(f"{'#':>4} | {'昵称':<40} | {'QQ号':>12} | 发言条数")
        print("-" * 65)
        for i, (qq, name, cnt) in enumerate(qualified, 1):
            disp_name = name[:40] if len(name) > 40 else name
            print(f"{i:>4} | {disp_name:<40} | {qq:>12} | {cnt:>6}")
    else:
        print("\n[无达标成员，无法抽奖!]")

    # 再打印未达标的
    if disqual:
        print(f"\n[未达标成员 ({len(disqual)} 人) —— 发言 < {min_msgs} 条]")
        print(f"{'#':>4} | {'昵称':<40} | {'QQ号':>12} | 发言条数")
        print("-" * 65)
        for i, (qq, name, cnt) in enumerate(disqual, 1):
            disp_name = name[:40] if len(name) > 40 else name
            print(f"{i:>4} | {disp_name:<40} | {qq:>12} | {cnt:>6}")

    return qualified


def draw_winners(qualified, top_n, seed_val):
    """从合格成员中随机抽取 top_n 人。"""
    rng = random.Random(seed_val)
    if len(qualified) < top_n:
        print(f"\n[警告：达标成员 ({len(qualified)}) 少于抽取人数 ({top_n})！将抽取全部 {len(qualified)} 人作为幸运用户。]\n")
        winners = list(qualified)
    else:
        winners = rng.sample(qualified, top_n)

    # 按原来排名排序（方便核对）
    rank_map = {qq: idx for idx, (qq, _, _) in enumerate(qualified, 1)}
    winners.sort(key=lambda x: rank_map.get(x[0], 9999))

    print("=" * 65)
    print("🎉 幸运用户名单 🎉")
    print("=" * 65)
    print(f"随机种子 : {seed_val}")
    print(f"抽样方法 : random.Random({seed_val}).sample(qualified, {top_n})")
    print(f"达标池大小 : {len(qualified)}")
    print("-" * 65)

    for i, (qq, name, cnt) in enumerate(winners, 1):
        disp_name = name[:40] if len(name) > 40 else name
        print(f"🏆 #{i}: {disp_name}  (QQ: {qq}, 发言 {cnt} 条)")

    print("=" * 65)
    return winners


def main():
    args = parse_args()

    # ===== 1. 计算时间窗口 =====
    if args.start_time is not None and args.end_time is not None:
        # 使用显式指定的时间戳
        start_ts = float(args.start_time)
        end_ts = float(args.end_time)
    elif args.hours is not None:
        now_ts = datetime.now(TIMEZONE_CN).timestamp()
        start_ts = now_ts - args.hours * 3600
        end_ts = now_ts
    else:
        # 默认行为：24 小时
        now_ts = datetime.now(TIMEZONE_CN).timestamp()
        start_ts = now_ts - 24 * 3600
        end_ts = now_ts

    # 格式化时间用于输出
    start_dt = datetime.fromtimestamp(start_ts, tz=TIMEZONE_CN)
    end_dt = datetime.fromtimestamp(end_ts, tz=TIMEZONE_CN)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    print()
    print("=" * 65)
    print("         群成员发言统计 + 幸运抽奖")
    print("=" * 65)
    print(f"数据源  : {os.path.abspath(args.db)}")
    print(f"目标群号: {args.group}")
    print(f"时间窗口: {start_str} ~ {end_str}")
    print(f"回溯时长: {args.hours or (end_ts - start_ts)/3600:.1f} 小时")
    print(f"阈值    : >= {args.min_msgs} 条发言")
    print(f"抽取人数: {args.top}")
    print(f"Bot QQ  : {args.bot_qq}")
    print("=" * 65)
    print()

    # ===== 2. 查询数据 =====
    rows = query_messages(args.db, args.group, start_ts, end_ts, args.bot_qq)
    total_senders = len(rows)
    total_msgs = sum(r[2] for r in rows)

    print(f"[数据概览] 该群在窗口内共 {total_msgs} 条消息,"
          f" {total_senders} 位不同发送者（已排除 bot）。")
    print()

    # ===== 3. 打印排行榜 =====
    qualified = print_ranking(rows, args.min_msgs)
    print()

    # ===== 4. 确定随机种子 =====
    seed_val = args.seed if args.seed is not None else int(datetime.now().timestamp())
    print(f"[随机种子] {seed_val} (时间戳={int(datetime.now().timestamp())})")
    print()

    # ===== 5. 抽奖 =====
    winners = draw_winners(qualified, args.top, seed_val)

    # ===== 6. 总结 =====
    print()
    if len(qualified) == 0:
        print("[结论] 无符合条件的成员，本次抽奖结束。")
    elif len(qualified) < args.top:
        print(f"[结论] 达标成员不足 {args.top} 人，实际抽取了 {len(qualified)} 人。")
    else:
        print(f"[结论] 从 {len(qualified)} 位达标成员中成功抽取 {args.top} 位幸运用户。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
