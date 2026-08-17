#!/usr/bin/env python3
"""
敏感信息过滤器 — 纯正则、无状态、按序替换策略

匹配顺序: 邮箱 → 手机号 → 身份证 → 银行卡 → IP → 地址
原则: 长模式优先、严格模式优先、先替换后匹配
"""

import re

# ── 预编译正则（模块级，只编译一次）──

# 邮箱: @ 符号特征唯一，最先匹配
EMAIL_RE = re.compile(
    r'(?<![a-zA-Z0-9._%+-])[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?![a-zA-Z0-9.-])'
)

# 手机号: 带分隔符 → 纯数字
PHONE_CLEAN_RE = re.compile(
    r'(\+?86[\s-]*)?(1[3-9]\d)[\s-]*(\d{4})[\s-]*(\d{4})'
)
PHONE_STRICT_RE = re.compile(
    r'(?<!\d)1[3-9]\d{9}(?!\d)'
)

# 身份证: 18位（含出生日期校验），严格模式优先于银行卡
ID_CARD_18_RE = re.compile(
    r'(?<!\d)'
    r'[1-9]\d{5}'                        # 前6位地址码
    r'(?:19|20)\d{2}'                    # 出生年份 1900-2099
    r'(?:0[1-9]|1[0-2])'                # 月份 01-12
    r'(?:0[1-9]|[12]\d|3[01])'           # 日期 01-31
    r'\d{3}[\dXx]'                       # 顺序码3位+校验码
    r'(?!\d)'
)

# 身份证: 15位旧版
ID_CARD_15_RE = re.compile(
    r'(?<!\d)'
    r'[1-9]\d{5}'                        # 前6位
    r'\d{2}'                             # 年份后2位
    r'(?:0[1-9]|1[0-2])'                # 月份
    r'(?:0[1-9]|[12]\d|3[01])'           # 日期
    r'\d{3}'                             # 顺序码
    r'(?!\d)'
)

# 银行卡: 带分隔符格式
BANK_CARD_FORMATTED_RE = re.compile(
    r'(?<!\d)(\d{4}[\s-]){3,4}\d{1,4}(?!\d)'
)

# 银行卡: 纯数字 16-19 位（身份证已经先匹配，不会冲突）
BANK_CARD_RAW_RE = re.compile(
    r'(?<!\d)\d{16,19}(?!\d)'
)

# IPv4
IPV4_RE = re.compile(
    r'(?<!\d)'
    r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'
    r'(?!\d)'
)

# 地址关键词
ADDRESS_KEYWORDS = [
    '省', '市', '区', '县', '镇', '乡', '村', '路', '街', '巷',
    '号', '栋', '单元', '楼', '室', '小区', '花园', '大厦', '广场',
]

# 快速路径预检：文本中是否包含数字或 @
DIGIT_OR_AT_RE = re.compile(r'[\d@]')


class SensitiveFilter:
    """敏感信息过滤器 — 无状态、纯正则、按序替换"""

    def __init__(self, config: dict):
        types = config.get("sensitive_filter", {}).get("types", {})
        self._enabled = config.get("sensitive_filter", {}).get("enabled", True)

        self._email_enabled = types.get("email", {}).get("enabled", True)
        self._phone_enabled = types.get("phone", {}).get("enabled", True)
        self._id_card_enabled = types.get("id_card", {}).get("enabled", True)
        self._bank_card_enabled = types.get("bank_card", {}).get("enabled", True)
        self._ip_enabled = types.get("ip_address", {}).get("enabled", False)
        self._address_enabled = types.get("address", {}).get("enabled", False)

        self._email_rpl = types.get("email", {}).get("replacement", "[邮箱]")
        self._phone_rpl = types.get("phone", {}).get("replacement", "[手机号]")
        self._id_card_rpl = types.get("id_card", {}).get("replacement", "[身份证号]")
        self._bank_card_rpl = types.get("bank_card", {}).get("replacement", "[银行卡号]")
        self._ip_rpl = types.get("ip_address", {}).get("replacement", "[IP地址]")
        self._addr_rpl = types.get("address", {}).get("replacement", "[地址]")

    def mask(self, text: str) -> str:
        if not self._enabled:
            return text
        if not DIGIT_OR_AT_RE.search(text):
            return text

        result = text

        if self._email_enabled:
            result = EMAIL_RE.sub(self._email_rpl, result)

        if self._phone_enabled:
            result = PHONE_CLEAN_RE.sub(self._phone_rpl, result)
            result = PHONE_STRICT_RE.sub(self._phone_rpl, result)

        if self._id_card_enabled:
            result = ID_CARD_18_RE.sub(self._id_card_rpl, result)
            result = ID_CARD_15_RE.sub(self._id_card_rpl, result)

        if self._bank_card_enabled:
            result = BANK_CARD_FORMATTED_RE.sub(self._bank_card_rpl, result)
            result = BANK_CARD_RAW_RE.sub(self._bank_card_rpl, result)

        if self._ip_enabled:
            result = IPV4_RE.sub(self._ip_rpl, result)

        if self._address_enabled:
            result = self._mask_address(result)

        return result

    def _mask_address(self, text: str) -> str:
        sentences = re.split(r'[。，,；;！!？?\n]', text)
        parts = []
        for sent in sentences:
            kw_count = sum(1 for kw in ADDRESS_KEYWORDS if kw in sent)
            parts.append(self._addr_rpl if kw_count >= 2 else sent)
        return '，'.join(parts)
