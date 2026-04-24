#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2019 n+e
# SPDX-License-Identifier: MIT
# See LICENSE file for full license text.
"""
通用 SSO 登录模块 - 浏览器辅助认证

通过 Selenium 自动化浏览器完成登录，提取认证信息供后续请求使用。
"""

import json
import os
import time
import uuid
from typing import Dict, List, Optional, Any

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


class SSOLogin:
    """
    通用 SSO 登录类

    功能:
    - 浏览器自动化登录
    - Cookie 提取和会话创建
    - 会话持久化存储
    - 设备指纹管理
    """

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    def __init__(
        self,
        login_url: str,
        success_indicators: List[str],
        username: Optional[str] = None,
        headless: bool = False,
        browser: str = "chrome",
        timeout: int = 300,
        headers: Optional[Dict[str, str]] = None,
        cookie_domains: Optional[List[str]] = None,
        username_input_id: str = "i_user",
        xsrf_token_name: str = "XSRF-TOKEN",
        xsrf_header_name: str = "X-XSRF-TOKEN",
    ):
        self.login_url = login_url
        self.success_indicators = success_indicators
        self.username = username
        self.headless = headless
        self.browser = browser.lower()
        self.timeout = timeout
        self.username_input_id = username_input_id
        self.xsrf_token_name = xsrf_token_name
        self.xsrf_header_name = xsrf_header_name
        self.headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        self.cookie_domains = cookie_domains or []

        self._driver: Optional[webdriver.Remote] = None
        self._session: Optional[requests.Session] = None
        self._cookies: Dict[str, str] = {}
        self._fingerprint: Optional[Dict[str, Any]] = None

    def _init_browser(self) -> bool:
        """初始化浏览器实例"""
        try:
            if self.browser == "chrome":
                options = ChromeOptions()
                if self.headless:
                    options.add_argument("--headless")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-gpu")
                options.add_argument(f"--user-agent={self.headers['User-Agent']}")
                self._driver = webdriver.Chrome(options=options)
            elif self.browser == "firefox":
                options = FirefoxOptions()
                if self.headless:
                    options.add_argument("--headless")
                self._driver = webdriver.Firefox(options=options)
            else:
                raise ValueError(f"不支持的浏览器类型: {self.browser}")

            self._driver.set_page_load_timeout(30)
            self._driver.implicitly_wait(10)
            print(f"[OK] {self.browser.upper()} 浏览器已启动")
            return True
        except WebDriverException as exc:
            print(f"[ERROR] 启动浏览器失败: {exc}")
            return False

    def _generate_fingerprint(self) -> Dict[str, Any]:
        """生成设备指纹数据"""
        return {
            "fingerPrint": str(uuid.uuid4()).replace("-", ""),
            "fingerGenPrint": f"gen{int(time.time())}",
            "timestamp": time.time(),
        }

    def _wait_for_login(self) -> bool:
        """等待用户在浏览器中完成登录"""
        print("[INFO] 请在浏览器中完成登录...")
        print("[INFO] 登录成功后程序会自动继续")

        start_time = time.time()
        last_url = ""

        while time.time() - start_time < self.timeout:
            try:
                current_url = self._driver.current_url
                page_source = self._driver.page_source

                if current_url != last_url:
                    print(f"[INFO] 页面跳转: {current_url[:80]}...")
                    last_url = current_url

                if any(indicator in current_url for indicator in self.success_indicators):
                    print("[OK] 检测到登录成功！")
                    time.sleep(3)
                    return True

                if any(indicator in page_source for indicator in self.success_indicators):
                    print("[OK] 检测到登录成功！")
                    time.sleep(3)
                    return True

                time.sleep(2)
            except Exception as exc:
                print(f"[WARN] 检查登录状态时出错: {exc}")
                time.sleep(2)

        print("[ERROR] 等待登录超时")
        return False

    def _extract_cookies(self) -> bool:
        """从浏览器提取 Cookies"""
        try:
            browser_cookies = self._driver.get_cookies()
            self._cookies = {cookie["name"]: cookie["value"] for cookie in browser_cookies}
            print(f"[OK] 提取到 {len(self._cookies)} 个 Cookies")

            for name in [self.xsrf_token_name, "JSESSIONID", "PHPSESSID"]:
                if name in self._cookies:
                    value = self._cookies[name]
                    display_val = value[:30] + "..." if len(value) > 30 else value
                    print(f"  - {name}: {display_val}")

            return True
        except Exception as exc:
            print(f"[ERROR] 提取 Cookies 失败: {exc}")
            return False

    def _create_session(self) -> bool:
        """使用提取的 Cookies 创建 requests 会话"""
        try:
            self._session = requests.Session()
            self._session.headers.update(self.headers)

            browser_cookies = self._driver.get_cookies()

            for cookie in browser_cookies:
                domain = cookie.get("domain", "")
                target_domains = self.cookie_domains if self.cookie_domains else [domain]

                for target_domain in target_domains:
                    self._session.cookies.set(
                        name=cookie["name"],
                        value=cookie["value"],
                        domain=target_domain,
                        path=cookie.get("path", "/"),
                        secure=cookie.get("secure", False),
                    )

            xsrf_token = self._cookies.get(self.xsrf_token_name)
            if xsrf_token:
                self._session.headers[self.xsrf_header_name] = xsrf_token
                print(f"[OK] 已设置 {self.xsrf_header_name}")

            print("[OK] 会话创建成功")
            return True
        except Exception as exc:
            print(f"[ERROR] 创建会话失败: {exc}")
            return False

    def login(
        self,
        verify: bool = False,
        verify_url: Optional[str] = None,
    ) -> Optional[requests.Session]:
        """
        执行完整的登录流程

        Args:
            verify: 是否验证会话有效性
            verify_url: 用于验证的测试 URL

        Returns:
            认证成功返回 requests.Session，失败返回 None
        """
        print("[INFO] 启动登录流程...")
        self._fingerprint = self._generate_fingerprint()

        if not self._init_browser():
            return None

        try:
            print(f"[INFO] 正在打开登录页面: {self.login_url}")
            self._driver.get(self.login_url)

            if self.username:
                try:
                    input_elem = WebDriverWait(self._driver, 10).until(
                        EC.presence_of_element_located((By.ID, self.username_input_id))
                    )
                    input_elem.clear()
                    input_elem.send_keys(self.username)
                    print(f"[OK] 已自动填入用户名: {self.username}")
                except TimeoutException:
                    print(f"[WARN] 未找到用户名输入框 (ID: {self.username_input_id})")

            if not self._wait_for_login():
                return None

            if not self._extract_cookies():
                return None

            if not self._create_session():
                return None

            if verify and verify_url and not self.verify_session(verify_url):
                print("[WARN] 会话验证失败")

            print("[OK] 登录完成！")
            return self._session
        except Exception as exc:
            print(f"[ERROR] 登录过程中出错: {exc}")
            return None
        finally:
            self.close_browser()

    @property
    def session(self) -> Optional[requests.Session]:
        """获取当前会话对象"""
        return self._session

    @property
    def cookies(self) -> Dict[str, str]:
        """获取当前 Cookies"""
        return self._cookies

    def verify_session(self, test_url: str) -> bool:
        """
        验证当前会话是否有效

        Args:
            test_url: 测试请求的 URL

        Returns:
            会话有效返回 True
        """
        if not self._session:
            return False

        try:
            response = self._session.get(test_url)
            print(f"[INFO] 验证响应状态码: {response.status_code}")

            if response.status_code == 200 and "login" not in response.url.lower():
                print("[OK] 会话验证成功")
                return True

            print("[WARN] 会话可能已过期")
            return False
        except Exception as exc:
            print(f"[ERROR] 验证会话时出错: {exc}")
            return False

    def save_session(self, filepath: str = "session.json") -> bool:
        """
        将会话信息保存到文件

        Args:
            filepath: 保存路径

        Returns:
            保存成功返回 True
        """
        if not self._session or not self._cookies:
            print("[ERROR] 没有可保存的会话")
            return False

        try:
            session_data = {
                "username": self.username,
                "cookies": self._cookies,
                "fingerprint": self._fingerprint,
                "headers": dict(self._session.headers),
                "cookie_domains": self.cookie_domains,
                "timestamp": time.time(),
            }

            with open(filepath, "w", encoding="utf-8") as fp:
                json.dump(session_data, fp, indent=2, ensure_ascii=False)

            print(f"[OK] 会话已保存到: {filepath}")
            return True
        except Exception as exc:
            print(f"[ERROR] 保存会话失败: {exc}")
            return False

    @classmethod
    def load_session(cls, filepath: str = "session.json") -> Optional[requests.Session]:
        """
        从文件加载已保存的会话

        Args:
            filepath: 会话文件路径

        Returns:
            加载成功返回 requests.Session，失败返回 None
        """
        try:
            with open(filepath, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            session = requests.Session()
            session.headers.update(data.get("headers", cls.DEFAULT_HEADERS))

            cookies = data.get("cookies", {})
            xsrf_token = cookies.get("XSRF-TOKEN") or cookies.get("xsrf-token")
            if xsrf_token:
                session.headers["X-XSRF-TOKEN"] = xsrf_token

            cookie_domains = data.get("cookie_domains", [""])
            for name, value in cookies.items():
                if value is None:
                    continue
                for domain in cookie_domains:
                    session.cookies.set(name=name, value=value, domain=domain, path="/")

            print(f"[OK] 会话已从 {filepath} 加载")
            return session
        except FileNotFoundError:
            print(f"[ERROR] 会话文件不存在: {filepath}")
            return None
        except Exception as exc:
            print(f"[ERROR] 加载会话失败: {exc}")
            return None

    def close_browser(self):
        """关闭浏览器实例"""
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            finally:
                self._driver = None

    def close(self):
        """释放所有资源"""
        self.close_browser()
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            finally:
                self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class TsinghuaSSOLogin(SSOLogin):
    """
    清华大学网络学堂专用登录类

    预配置了清华 SSO 的登录参数
    """

    LOGIN_URL = (
        "https://id.tsinghua.edu.cn/do/off/ui/auth/login/form/"
        "bb5df85216504820be7bba2b0ae1535b/0"
    )
    SUCCESS_INDICATORS = [
        "learn.tsinghua.edu.cn",
        "myCourse",
        "semesterCourseList",
        "退出登录",
    ]
    COOKIE_DOMAINS = [
        ".tsinghua.edu.cn",
        "learn.tsinghua.edu.cn",
        "id.tsinghua.edu.cn",
    ]

    def __init__(
        self,
        username: Optional[str] = None,
        headless: bool = False,
        browser: str = "chrome",
    ):
        super().__init__(
            login_url=self.LOGIN_URL,
            success_indicators=self.SUCCESS_INDICATORS,
            username=username,
            headless=headless,
            browser=browser,
            cookie_domains=self.COOKIE_DOMAINS,
        )

    def get_courses(self) -> List[Dict[str, Any]]:
        """获取当前学期的课程列表"""
        if not self._session:
            print("[ERROR] 未登录")
            return []

        try:
            resp = self._session.get(
                "https://learn.tsinghua.edu.cn/b/kc/zhjw_v_code_xnxq/getCurrentAndNextSemester"
            )
            semester_id = resp.json()["result"]["xnxq"]

            resp = self._session.get(
                f"https://learn.tsinghua.edu.cn/b/wlxt/kc/v_wlkc_xs_xkb_kcb_extend/"
                f"student/loadCourseBySemesterId/{semester_id}/zh"
            )
            courses = resp.json()["resultList"]
            print(f"[OK] 获取到 {len(courses)} 门课程")
            return courses
        except Exception as exc:
            print(f"[ERROR] 获取课程失败: {exc}")
            return []
