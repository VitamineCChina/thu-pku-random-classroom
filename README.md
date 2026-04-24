# THU-PKU-Random-Classroom - 清华/北大空闲教室查询工具

随机选择清华大学或北京大学的空闲教室，支持命令行交互和缓存机制。

## 功能特性

- 支持清华大学、北京大学或两校混合查询
- 自动检测当前学期与周次
- 浏览器辅助 SSO 登录（清华）
- 本地缓存避免重复登录
- 按时间段、座位数筛选教室

## 环境要求

- Python 3.8+
- Chrome 或 Firefox 浏览器（用于 SSO 登录）
- 对应浏览器 WebDriver（如 chromedriver）

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本用法

```bash
# 查询当前时间的空闲教室（两校）
python random_classroom_unified.py

# 指定时间查询
python random_classroom_unified.py --time 14:30

# 仅查询清华
python random_classroom_unified.py --thu

# 仅查询北大
python random_classroom_unified.py --pku

# 设置最小座位数
python random_classroom_unified.py --min-capacity 50

# 手动指定周次（跳过自动检测）
python random_classroom_unified.py --week 10

# 手动指定学期
python random_classroom_unified.py --semester 2025-2026-2

# 禁用缓存，强制重新获取数据
python random_classroom_unified.py --no-cache

# 清除本地缓存
python random_classroom_unified.py --clear-cache
```

### 命令行参数

| 参数 | 缩写 | 说明 | 默认值 |
|------|------|------|--------|
| `--time` | `-t` | 查询时间 (HH:MM) | 当前时间 |
| `--thu` | - | 仅查询清华 | False |
| `--pku` | - | 仅查询北大 | False |
| `--both` | - | 查询两校 | True |
| `--min-capacity` | `-c` | 最小座位数 | 不限制 |
| `--week` | `-w` | 清华周次 | 自动检测 |
| `--semester` | - | 清华学期编码 | 自动检测 |
| `--no-cache` | - | 禁用缓存 | False |
| `--clear-cache` | - | 清除缓存后退出 | False |

### 作为模块调用

```python
from sso_login import SSOLogin, TsinghuaSSOLogin
from random_classroom_unified import find_random_classroom

# 方式一：使用通用 SSO 登录
login = SSOLogin(
    login_url="https://your-sso-site.com/login",
    success_indicators=["dashboard"],
)
session = login.login()

# 方式二：使用清华专用登录类
thu_login = TsinghuaSSOLogin(username="your_student_id")
session = thu_login.login()

# 查询空闲教室
result = find_random_classroom(
    time_str="14:30",
    include_thu=True,
    include_pku=True,
    session=session,
    min_capacity=30,
)

print(result["selected"])
```

## 项目结构

```
./
├── sso_login.py                 # SSO 登录模块
│   ├── SSOLogin                  #   通用 SSO 登录类
│   └── TsinghuaSSOLogin          #   清华专用登录类
├── random_classroom_unified.py   # 教室查询主程序
├── requirements.txt              # Python 依赖
├── README.md                     # 本文件
└── .cache/                       # 运行时缓存目录（自动生成）
    └── thu_classrooms.json       # 清华教室数据缓存
```

## 时间段说明

### 清华大学（6 大节）

| 节次 | 时间 |
|------|------|
| 第 1 大节 | 08:00 - 09:35 |
| 第 2 大节 | 09:50 - 12:15 |
| 第 3 大节 | 13:30 - 15:05 |
| 第 4 大节 | 15:20 - 16:55 |
| 第 5 大节 | 17:10 - 18:45 |
| 第 6 大节 | 19:20 - 21:45 |

### 北京大学（12 节）

| 节次 | 时间 |
|------|------|
| 第 1 节 | 08:00 - 08:50 |
| ... | ... |
| 第 12 节 | 20:40 - 21:30 |

## 注意事项

1. **首次使用清华查询**需要通过浏览器完成 SSO 登录，登录成功后会自动缓存会话
2. **北大查询**无需登录，直接访问公开接口
3. 缓存按日期+周次校验，同一天内重复查询不会触发重新登录
4. 如遇登录问题，可使用 `--clear-cache` 清除缓存后重试
