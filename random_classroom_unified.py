#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2025 Stone
# SPDX-License-Identifier: MIT
# See LICENSE file for full license text.
"""
清华 / 北大空闲教室随机选择工具

支持选择清华、北大或两校混合的空闲教室查询。
支持缓存机制，避免重复登录。
"""

import argparse
import json
import os
import random
import urllib3
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")
THU_CACHE_FILE = os.path.join(CACHE_DIR, "thu_classrooms.json")


# ============================================
# 时间段配置
# ============================================

THU_TIME_SLOTS = [
    (time(8, 0), time(9, 35)),
    (time(9, 50), time(12, 15)),
    (time(13, 30), time(15, 5)),
    (time(15, 20), time(16, 55)),
    (time(17, 10), time(18, 45)),
    (time(19, 20), time(21, 45)),
]

PKU_TIME_SLOTS = [
    (time(8, 0), time(8, 50)),
    (time(9, 0), time(9, 50)),
    (time(10, 10), time(11, 0)),
    (time(11, 10), time(12, 0)),
    (time(13, 0), time(13, 50)),
    (time(14, 0), time(14, 50)),
    (time(15, 10), time(16, 0)),
    (time(16, 10), time(17, 0)),
    (time(17, 10), time(18, 0)),
    (time(18, 40), time(19, 30)),
    (time(19, 40), time(20, 30)),
    (time(20, 40), time(21, 30)),
]

THU_SLOT_NAMES = [f"第{i}大节" for i in range(1, 7)]
PKU_SLOT_NAMES = [f"第{i}节" for i in range(1, 13)]

SCHOOL_THU = "清华"
SCHOOL_PKU = "北大"

STATUS_AVAILABLE = "空闲"
STATUS_OCCUPIED = "有课"
STATUS_EXAM = "考试"
STATUS_BORROWED = "借用"
STATUS_DISABLED = "屏蔽"


# ============================================
# 数据模型
# ============================================

@dataclass
class Classroom:
    """教室信息数据类"""

    name: str
    capacity: int
    school: str
    building: str
    status_list: List[str]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "capacity": self.capacity,
            "school": self.school,
            "building": self.building,
            "status_list": self.status_list,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Classroom":
        return cls(
            name=data["name"],
            capacity=data["capacity"],
            school=data["school"],
            building=data["building"],
            status_list=data["status_list"],
        )


# ============================================
# 学期与周次检测
# ============================================

def get_semester_id() -> str:
    """
    根据当前日期自动判断清华学年学期编码

    Returns:
        学期字符串，如 "2025-2026-2"
    """
    now = datetime.now()
    year = now.year
    month = now.month

    if month < 7:
        suffix = "-2"
    elif month <= 8:
        suffix = "-3"
    else:
        suffix = "-1"

    start_year = year if month >= 9 else year - 1
    return f"{start_year}-{start_year + 1}{suffix}"


def parse_monday_from_html(html_content: str) -> Optional[date]:
    """
    从教室查询 HTML 中解析本周周一的日期

    Args:
        html_content: 教室查询页面 HTML 内容

    Returns:
        周一的 date 对象，解析失败返回 None
    """
    import re

    match = re.search(r'一\((\d{2})\.(\d{2})\)', html_content)
    if not match:
        return None

    try:
        month, day = int(match.group(1)), int(match.group(2))
        now = datetime.now()
        return date(now.year, month, day)
    except (ValueError, TypeError):
        return None


def resolve_current_week(session: requests.Session, semester_id: str) -> Tuple[Optional[int], Optional[date]]:
    """
    通过查询第 1 周的教室数据获取学期起始周一日期，计算当前周次

    Args:
        session: 已认证的 requests 会话
        semester_id: 学期字符串

    Returns:
        Tuple[当前周次, 周一日期]，解析失败返回 (None, None)
    """
    url = (
        f"https://zhjw.cic.tsinghua.edu.cn/pk.classroomctrl.do"
        f"?m=qyClassroomState&xnxq={semester_id}&weeknumber=1"
        f"&jslxm=&classroom=&skzws_min=&skzws_max=&jsgllx=xgjs"
    )
    response = session.get(url, verify=False)
    response.encoding = "gbk"
    monday_date = parse_monday_from_html(response.text)

    if monday_date is None:
        print("[WARN] 无法从第 1 周数据解析周一日期")
        return None, None

    today = date.today()
    days_diff = (today - monday_date).days
    current_week = max(days_diff // 7 + 1, 1)

    print(f"[INFO] 第 1 周周一: {monday_date}, 当前: 第 {current_week} 周")
    return current_week, monday_date


# ============================================
# 缓存管理
# ============================================

def save_thu_cache(classrooms: List[Classroom], week_num: int, monday_date: Optional[date] = None):
    """保存清华教室数据到缓存文件"""
    os.makedirs(CACHE_DIR, exist_ok=True)

    cache_data = {
        "date": date.today().isoformat(),
        "week": week_num,
        "weekday": datetime.now().weekday(),
        "monday_date": monday_date.isoformat() if monday_date else None,
        "classrooms": [c.to_dict() for c in classrooms],
        "timestamp": datetime.now().isoformat(),
    }

    with open(THU_CACHE_FILE, "w", encoding="utf-8") as fp:
        json.dump(cache_data, fp, ensure_ascii=False, indent=2)

    print(f"[OK] 清华教室数据已缓存到: {THU_CACHE_FILE}")


def load_thu_cache(week_num: int) -> Optional[List[Classroom]]:
    """
    从缓存加载清华教室数据

    Args:
        week_num: 当前周次（用于验证缓存有效性）

    Returns:
        缓存有效返回教室列表，否则返回 None
    """
    if not os.path.exists(THU_CACHE_FILE):
        return None

    try:
        with open(THU_CACHE_FILE, "r", encoding="utf-8") as fp:
            cache_data = json.load(fp)

        today_str = date.today().isoformat()
        cached_date = cache_data.get("date")
        cached_week = cache_data.get("week")

        if cached_date == today_str and cached_week == week_num:
            classrooms = [Classroom.from_dict(c) for c in cache_data["classrooms"]]
            print(f"[OK] 使用缓存的清华教室数据 (缓存时间: {cache_data.get('timestamp')})")
            return classrooms

        return None
    except Exception as exc:
        print(f"[WARN] 读取缓存失败: {exc}")
        return None


def load_cached_monday() -> Optional[date]:
    """
    从缓存中读取学期第一周周一日期

    Returns:
        周一 date 对象，不存在或无效返回 None
    """
    if not os.path.exists(THU_CACHE_FILE):
        return None

    try:
        with open(THU_CACHE_FILE, "r", encoding="utf-8") as fp:
            cache_data = json.load(fp)

        monday_str = cache_data.get("monday_date")
        return date.fromisoformat(monday_str) if monday_str else None
    except Exception:
        return None


# ============================================
# 时间工具函数
# ============================================

def get_slot_index(
    time_str: str,
    slot_definitions: List[Tuple[time, time]],
) -> Tuple[int, bool]:
    """
    根据时间字符串获取时间段索引

    Args:
        time_str: 时间字符串，格式 "HH:MM"
        slot_definitions: 时间段定义列表

    Returns:
        Tuple[索引, 是否在时间段内]
    """
    try:
        hour, minute = map(int, time_str.split(":"))
        query_time = time(hour, minute)
    except ValueError:
        raise ValueError(f"无效的时间格式: {time_str}，请使用 HH:MM 格式")

    for idx, (start, end) in enumerate(slot_definitions):
        if start <= query_time <= end:
            return idx, True

    for idx, (start, _end) in enumerate(slot_definitions):
        if query_time < start:
            return idx, False

    return -1, False


def format_time_info(time_str: str, school_mode: str = "both") -> str:
    """格式化时间与对应课程段信息"""
    thu_idx, thu_active = get_slot_index(time_str, THU_TIME_SLOTS)
    pku_idx, pku_active = get_slot_index(time_str, PKU_TIME_SLOTS)

    lines = [f"查询时间: {time_str}"]

    if school_mode in (SCHOOL_THU, "both"):
        if thu_idx >= 0:
            status_text = "上课中" if thu_active else "即将开始"
            lines.append(f"清华: {THU_SLOT_NAMES[thu_idx]} ({status_text})")
        else:
            lines.append("清华: 已无课程时间段")

    if school_mode in (SCHOOL_PKU, "both"):
        if pku_idx >= 0:
            status_text = "上课中" if pku_active else "即将开始"
            lines.append(f"北大: {PKU_SLOT_NAMES[pku_idx]} ({status_text})")
        else:
            lines.append("北大: 已无课程时间段")

    return "\n".join(lines)


# ============================================
# 清华教室数据获取
# ============================================

THU_STATUS_CLASS_MAP = {
    "onteaching": STATUS_OCCUPIED,
    "onexam": STATUS_EXAM,
    "onborrowed": STATUS_BORROWED,
    "ondisabled": STATUS_DISABLED,
    "available": STATUS_AVAILABLE,
}


def parse_thu_html(html_content: str) -> List[Classroom]:
    """从 HTML 解析清华教室数据"""
    soup = BeautifulSoup(html_content, "html.parser")
    scroll_div = soup.find("div", id="scrollContent")
    if not scroll_div:
        return []

    table = scroll_div.find("table")
    if not table:
        return []

    rows = []
    for tbody in table.find_all("tbody"):
        rows.extend(tbody.find_all("tr"))

    classrooms = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        building = cells[0].contents[0].strip()
        room_info = cells[0].contents[2].strip()

        if ":" not in room_info:
            continue

        room_name = room_info.split(":")[0].strip()
        capacity_str = room_info.split(":")[1].strip()

        try:
            capacity = int("".join(filter(str.isdigit, capacity_str)))
        except ValueError:
            capacity = 0

        status_list = []
        for cell in cells[1:]:
            cell_status = STATUS_AVAILABLE
            for css_class, status_text in THU_STATUS_CLASS_MAP.items():
                if css_class in cell.get("class", []):
                    cell_status = status_text
                    break
            status_list.append(cell_status)

        classrooms.append(Classroom(
            name=room_name,
            capacity=capacity,
            school=SCHOOL_THU,
            building=building,
            status_list=status_list,
        ))

    return classrooms


def fetch_thu_classrooms(
    session: Optional[requests.Session],
    week_num: int,
    semester_id: Optional[str] = None,
    use_cache: bool = True,
    save_to_cache: bool = True,
    monday_date: Optional[date] = None,
) -> List[Classroom]:
    """
    获取清华教室数据

    Args:
        session: 登录会话（使用缓存时可为 None）
        week_num: 周次
        semester_id: 学期字符串，为 None 则自动检测
        use_cache: 是否读取缓存
        save_to_cache: 是否写入缓存
        monday_date: 学期第一周周一日期

    Returns:
        教室列表
    """
    if semester_id is None:
        semester_id = get_semester_id()

    if use_cache:
        cached = load_thu_cache(week_num)
        if cached is not None:
            return cached

    if session is None:
        raise ValueError("清华教室数据需要登录获取，请提供有效的 session")

    print(f"[INFO] 正在从清华服务器获取教室数据 (学期: {semester_id}, 第 {week_num} 周)...")

    url = (
        f"https://zhjw.cic.tsinghua.edu.cn/pk.classroomctrl.do"
        f"?m=qyClassroomState&xnxq={semester_id}&weeknumber={week_num}"
        f"&jslxm=&classroom=&skzws_min=&skzws_max=&jsgllx=xgjs"
    )
    response = session.get(url, verify=False)
    response.encoding = "gbk"
    classrooms = parse_thu_html(response.text)

    if save_to_cache and classrooms:
        save_thu_cache(classrooms, week_num, monday_date=monday_date)

    return classrooms


# ============================================
# 北大教室数据获取
# ============================================

PKU_BUILDING_LIST = ["一教", "二教", "三教", "四教", "理教", "文史", "哲学", "地学", "国关", "政管"]
PKU_DAY_OPTIONS = ["今天", "明天", "后天"]


def fetch_pku_classrooms(day_option: str = "今天") -> List[Classroom]:
    """
    获取北大教室数据

    Args:
        day_option: 日期选项 ("今天" / "明天" / "后天")

    Returns:
        教室列表
    """
    classrooms = []

    for building in PKU_BUILDING_LIST:
        try:
            url = (
                f"https://portal.pku.edu.cn/publicQuery/classroomQuery/"
                f"retrClassRoomFree.do?buildingName={building}&time={day_option}"
            )
            response = requests.get(url, timeout=10)
            data = response.json()

            if not data.get("success"):
                continue

            for row in data.get("rows", []):
                room_number = row.get("room", "")
                capacity = int(row.get("cap", 0))

                status_list = []
                for i in range(1, 13):
                    cell_status = row.get(f"c{i}", "")
                    status_list.append(STATUS_OCCUPIED if cell_status == "占用" else STATUS_AVAILABLE)

                classrooms.append(Classroom(
                    name=f"{building}{room_number}",
                    capacity=capacity,
                    school=SCHOOL_PKU,
                    building=building,
                    status_list=status_list,
                ))
        except Exception as exc:
            print(f"[WARN] 获取北大 {building} 教室失败: {exc}")
            continue

    return classrooms


# ============================================
# 教室筛选逻辑
# ============================================

def filter_available(
    classrooms: List[Classroom],
    slot_index: int,
    day_offset: int = 0,
) -> List[Classroom]:
    """
    筛选指定时间段空闲的教室

    Args:
        classrooms: 教室列表
        slot_index: 时间段索引
        day_offset: 天数偏移（仅清华有效）

    Returns:
        空闲教室列表
    """
    if slot_index < 0:
        return []

    available = []
    for classroom in classrooms:
        if classroom.school == SCHOOL_THU:
            position = day_offset * 6 + slot_index
            if position < len(classroom.status_list) and classroom.status_list[position] == STATUS_AVAILABLE:
                available.append(classroom)
        elif classroom.school == SCHOOL_PKU:
            if slot_index < len(classroom.status_list) and classroom.status_list[slot_index] == STATUS_AVAILABLE:
                available.append(classroom)

    return available


def pick_random_classroom(
    classrooms: List[Classroom],
    slot_index: int,
    day_offset: int = 0,
    min_capacity: Optional[int] = None,
    school_filter: Optional[str] = None,
) -> Optional[Classroom]:
    """
    从空闲教室中随机选择一个

    Args:
        classrooms: 教室列表
        slot_index: 时间段索引
        day_offset: 天数偏移
        min_capacity: 最小座位数
        school_filter: 学校筛选

    Returns:
        随机选中的教室，无符合条件则返回 None
    """
    available = filter_available(classrooms, slot_index, day_offset)

    if min_capacity is not None:
        available = [c for c in available if c.capacity >= min_capacity]

    if school_filter:
        available = [c for c in available if c.school == school_filter]

    return random.choice(available) if available else None


# ============================================
# 主查询入口
# ============================================

def find_random_classroom(
    time_str: str,
    include_thu: bool = True,
    include_pku: bool = True,
    min_capacity: Optional[int] = None,
    session: Optional[requests.Session] = None,
    week_num: Optional[int] = None,
    semester_id: Optional[str] = None,
    pku_day: str = "今天",
    use_cache: bool = True,
) -> Dict:
    """
    随机选择空闲教室的主入口函数

    Args:
        time_str: 查询时间，格式 "HH:MM"
        include_thu: 是否包含清华
        include_pku: 是否包含北大
        min_capacity: 最小座位数
        session: 清华登录会话
        week_num: 清华周次（None 则自动检测）
        semester_id: 清华学期编码（None 则自动检测）
        pku_day: 北大日期选项
        use_cache: 是否使用缓存

    Returns:
        包含查询结果的字典
    """
    if semester_id is None:
        semester_id = get_semester_id()

    result = {
        "query_time": time_str,
        "include_thu": include_thu,
        "include_pku": include_pku,
        "selected": None,
        "available_count": 0,
        "thu_available": 0,
        "pku_available": 0,
        "error": None,
        "from_cache": False,
        "semester_id": semester_id,
        "week_num": week_num,
    }

    all_classrooms = []

    # ---- 清华教室获取 ----
    if include_thu:
        thu_slot_idx, _ = get_slot_index(time_str, THU_TIME_SLOTS)
        if thu_slot_idx < 0:
            result["error"] = "清华: 已过所有课程时间段"
            return result

        # 自动检测周次
        current_week = week_num
        monday_ref = None

        if current_week is None:
            cached_monday = load_cached_monday()
            if cached_monday is not None:
                today = date.today()
                current_week = max((today - cached_monday).days // 7 + 1, 1)
                monday_ref = cached_monday
                print(f"[INFO] 从缓存读取第 1 周周一: {cached_monday}, 当前: 第 {current_week} 周")
                result["week_num"] = current_week

            if current_week is None and session is not None:
                print("[INFO] 正在自动检测清华当前周次...")
                current_week, monday_ref = resolve_current_week(session, semester_id)
                if current_week is not None:
                    result["week_num"] = current_week
                else:
                    result["error"] = "无法自动检测周次，请使用 --week 参数手动指定"
                    return result
            elif current_week is None:
                result["error"] = "无法自动检测周次，请指定 --week 或先登录一次清华以建立缓存"
                return result

        try:
            thu_classrooms = fetch_thu_classrooms(
                session=session,
                week_num=current_week,
                semester_id=semester_id,
                use_cache=use_cache,
                monday_date=monday_ref,
            )

            if load_thu_cache(current_week) is not None:
                result["from_cache"] = True

            print(f"[OK] 获取到 {len(thu_classrooms)} 个清华教室")

            today_weekday = datetime.now().weekday()
            thu_available = filter_available(thu_classrooms, thu_slot_idx, today_weekday)
            result["thu_available"] = len(thu_available)
            all_classrooms.extend(thu_classrooms)
        except ValueError as exc:
            result["error"] = str(exc)
            return result

    # ---- 北大教室获取 ----
    if include_pku:
        pku_slot_idx, _ = get_slot_index(time_str, PKU_TIME_SLOTS)
        if pku_slot_idx < 0:
            if not include_thu:
                result["error"] = "北大: 已过所有课程时间段"
                return result
        else:
            pku_classrooms = fetch_pku_classrooms(pku_day)
            print(f"[OK] 获取到 {len(pku_classrooms)} 个北大教室")

            pku_available = filter_available(pku_classrooms, pku_slot_idx)
            result["pku_available"] = len(pku_available)
            all_classrooms.extend(pku_classrooms)

    # ---- 合并并筛选 ----
    final_available = []

    if include_thu:
        thu_slot_idx, _ = get_slot_index(time_str, THU_TIME_SLOTS)
        today_weekday = datetime.now().weekday()
        final_available.extend(filter_available(
            [c for c in all_classrooms if c.school == SCHOOL_THU],
            thu_slot_idx,
            today_weekday,
        ))

    if include_pku:
        pku_slot_idx, _ = get_slot_index(time_str, PKU_TIME_SLOTS)
        if pku_slot_idx >= 0:
            final_available.extend(filter_available(
                [c for c in all_classrooms if c.school == SCHOOL_PKU],
                pku_slot_idx,
            ))

    if min_capacity:
        final_available = [c for c in final_available if c.capacity >= min_capacity]

    result["available_count"] = len(final_available)

    if not final_available:
        result["error"] = "没有符合条件的空闲教室"
        return result

    selected = random.choice(final_available)
    result["selected"] = {
        "name": selected.name,
        "school": selected.school,
        "building": selected.building,
        "capacity": selected.capacity,
    }

    return result


# ============================================
# 命令行接口
# ============================================

def main():
    parser = argparse.ArgumentParser(description="随机选择清华/北大空闲教室")
    parser.add_argument("--time", "-t", default=None, help="查询时间 HH:MM（默认当前时间）")
    parser.add_argument("--thu", action="store_true", help="仅查询清华")
    parser.add_argument("--pku", action="store_true", help="仅查询北大")
    parser.add_argument("--both", action="store_true", default=True, help="查询两校（默认）")
    parser.add_argument("--min-capacity", "-c", type=int, help="最小座位数")
    parser.add_argument("--week", "-w", type=int, default=None, help="清华周次（不指定则自动检测）")
    parser.add_argument("--semester", type=str, default=None, help="清华学期（如 2025-2026-2）")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    parser.add_argument("--clear-cache", action="store_true", help="清除缓存后退出")

    args = parser.parse_args()

    query_time = args.time or datetime.now().strftime("%H:%M")

    if args.clear_cache:
        if os.path.exists(THU_CACHE_FILE):
            os.remove(THU_CACHE_FILE)
            print(f"[OK] 已清除缓存: {THU_CACHE_FILE}")
        else:
            print("[INFO] 缓存文件不存在")
        return

    include_thu = args.thu or args.both or (not args.thu and not args.pku)
    include_pku = args.pku or args.both or (not args.thu and not args.pku)
    use_cache = not args.no_cache
    semester_id = args.semester
    week_num = args.week

    # 打印查询信息
    print("=" * 50)
    print("清华/北大空闲教室随机选择")
    print(f"学期: {semester_id or '自动检测'}")
    print(f"周次: {'第 ' + str(week_num) + ' 周 (手动指定)' if week_num is not None else '自动检测'}")
    print("=" * 50)

    target_school = "both" if include_thu and include_pku else (SCHOOL_THU if include_thu else SCHOOL_PKU)
    print(format_time_info(query_time, target_school))
    print()

    # 清华登录处理
    login_session = None
    if include_thu:
        need_login = False
        cached_data = None

        effective_week = week_num
        if effective_week is None and use_cache:
            cached_monday = load_cached_monday()
            if cached_monday is not None:
                today = date.today()
                effective_week = max((today - cached_monday).days // 7 + 1, 1)

        if effective_week is not None:
            cached_data = load_thu_cache(effective_week) if use_cache else None

        if cached_data is not None and week_num is not None:
            print("[OK] 使用缓存的清华教室数据，无需登录")
        elif cached_data is not None and week_num is None:
            print(f"[OK] 缓存包含周一日期信息，已计算当前为第 {effective_week} 周，无需登录")
            cached_data = None
        elif cached_data is None:
            need_login = True

        if need_login:
            print("[INFO] 清华教室需要登录...")
            from sso_login import SSOLogin

            login_instance = SSOLogin(
                login_url=(
                    "https://id.tsinghua.edu.cn/do/off/ui/auth/login/form/"
                    "10000ea055dd8d81d09d5a1ba55d39ad"
                ),
                success_indicators=["info.tsinghua.edu.cn"],
            )
            login_session = login_instance.login()

            if not login_session:
                print("[ERROR] 清华登录失败")
                return

            csrf_token = login_session.cookies.get("XSRF-TOKEN")
            ticket_resp = login_session.get(
                f"https://info.tsinghua.edu.cn/b/yyfw/vyyfwxx/info/portal_fg/common/onlineAppRedirect"
                f"?yyfwid=40470BB47E0849E9EF717983490BC964&machine=p&_csrf={csrf_token}",
                verify=False,
            )
            ticket = ticket_resp.json()["object"]["roamingurl"].split("ticket=")[-1]
            login_session.get(
                f"https://zhjw.cic.tsinghua.edu.cn/j_acegi_login.do"
                f"?url=/pk.classroomctrl.do&m=roomStatusQYIndex&showtitle=0&ticket={ticket}",
                verify=False,
            )

    # 执行查询
    result = find_random_classroom(
        time_str=query_time,
        include_thu=include_thu,
        include_pku=include_pku,
        min_capacity=args.min_capacity,
        session=login_session,
        week_num=week_num,
        semester_id=semester_id,
        use_cache=use_cache,
    )

    # 输出结果
    print()
    print("=" * 50)
    if result["error"]:
        print(f"[ERROR] {result['error']}")
    elif result["selected"]:
        cache_tag = "(来自缓存)" if result.get("from_cache") else ""
        print(f"随机选择的空闲教室 {cache_tag}:")
        print(f"  学校: {result['selected']['school']}")
        print(f"  楼名: {result['selected']['building']}")
        print(f"  教室: {result['selected']['name']}")
        print(f"  容量: {result['selected']['capacity']} 人")
        print()
        print(f"学期: {result.get('semester_id', '未知')}, 周次: 第 {result.get('week_num', '?')} 周")
        print(f"总计空闲: {result['available_count']} 间")
        print(f"  - 清华: {result['thu_available']} 间")
        print(f"  - 北大: {result['pku_available']} 间")
    print("=" * 50)


if __name__ == "__main__":
    main()
