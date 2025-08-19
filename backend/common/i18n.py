#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import json
import os

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.core.conf import settings
from backend.core.path_conf import LOCALE_DIR

# 在模块级别导入，避免每次调用时重复导入
try:
    from backend.middleware.i18n_middleware import current_language_context

    _HAS_MIDDLEWARE = True
except ImportError:
    _HAS_MIDDLEWARE = False
    current_language_context = None


class I18n:
    """国际化管理器"""

    def __init__(self):
        self.locales: dict[str, dict[str, Any]] = {}
        self.current_language: str = settings.I18N_DEFAULT_LANGUAGE
        # 添加缓存用于存储已解析的键值对
        self._cache = {}
        # 用于缓存失效的哈希值
        self._locales_hash = 0
        # 创建专用的 LRU 缓存函数
        self._path_cache = lru_cache(maxsize=512)(self._get_translation_by_path_cached_impl)

    def load_locales(self):
        """加载语言文本"""
        patterns = [
            os.path.join(LOCALE_DIR, '*.json'),
            os.path.join(LOCALE_DIR, '*.yaml'),
            os.path.join(LOCALE_DIR, '*.yml'),
        ]

        lang_files = []

        for pattern in patterns:
            lang_files.extend(glob.glob(pattern))

        for lang_file in lang_files:
            with open(lang_file, 'r', encoding='utf-8') as f:
                lang = Path(lang_file).stem
                file_type = Path(lang_file).suffix[1:]
                match file_type:
                    case 'json':
                        self.locales[lang] = json.loads(f.read())
                    case 'yaml' | 'yml':
                        self.locales[lang] = yaml.full_load(f.read())

        # 更新哈希值并清空缓存，因为语言包已更新
        self._locales_hash = hash(str(self.locales))
        self.clear_cache()

    def _get_translation_by_path_cached_impl(self, lang: str, key: str) -> str | None:
        """
        LRU 缓存的实现函数

        :param lang: 语言代码
        :param key: 翻译键，支持点分隔
        :return: 翻译文本或 None
        """
        if lang not in self.locales:
            return None

        keys = key.split('.')
        translation = self.locales[lang]

        for k in keys:
            if isinstance(translation, dict) and k in translation:
                translation = translation[k]
            else:
                return None

        return translation if isinstance(translation, str) else None

    def _get_translation_by_path(self, lang: str, key: str) -> str | None:
        """
        通过路径获取翻译，使用优化的缓存机制

        :param lang: 语言代码
        :param key: 翻译键，支持点分隔
        :return: 翻译文本或 None
        """
        return self._path_cache(lang, key)

    def _parse_kwargs_optimized(self, kwargs: dict, current_lang: str) -> dict:
        """
        优化的 kwargs 解析方法

        :param kwargs: 原始参数
        :param current_lang: 当前语言
        :return: 解析后的参数
        """
        if not kwargs:
            return {}

        parsed_kwargs = {}
        for k, v in kwargs.items():
            if isinstance(v, str) and '.' in v:
                # 使用缓存的方法获取嵌套值
                val = self._get_translation_by_path(current_lang, v)
                parsed_kwargs[k] = val if val is not None else v
            else:
                parsed_kwargs[k] = v
        return parsed_kwargs

    def _create_cache_key(self, key: str, kwargs: dict, current_lang: str) -> tuple | None:
        """
        创建缓存键的优化版本

        :param key: 翻译键
        :param kwargs: 参数字典
        :param current_lang: 当前语言
        :return: 缓存键元组，如果参数过于复杂则返回 None
        """
        if not kwargs:
            return (current_lang, key, None)

        # 限制 kwargs 的复杂度，避免缓存键过大
        if len(kwargs) > 10:  # 限制参数数量
            return None

        # 检查参数值的大小，避免缓存键过大
        total_size = 0
        for k, v in kwargs.items():
            if isinstance(v, str):
                total_size += len(v)
            if total_size > 500:  # 限制总字符长度
                return None

        kwargs_tuple = tuple(sorted(kwargs.items()))
        return (current_lang, key, kwargs_tuple)

    def _evict_cache_if_needed(self):
        """
        LRU 风格的缓存清理机制
        """
        if len(self._cache) >= 1000:
            # 移除最旧的 20% 条目
            items_to_remove = len(self._cache) // 5
            keys_to_remove = list(self._cache.keys())[:items_to_remove]
            for key in keys_to_remove:
                del self._cache[key]

    def get_request_language(self) -> str:
        """
        获取当前请求的语言设置

        :return: 当前语言代码
        """
        if _HAS_MIDDLEWARE and current_language_context is not None:
            try:
                return current_language_context.get()
            except LookupError:
                # 如果不在请求上下文中，使用默认语言
                return self.current_language
        else:
            # 如果中间件未导入或不可用，使用默认语言
            return self.current_language

    def t(self, key: str, default: Any | None = None, **kwargs) -> str:
        """
        优化的翻译函数

        :param key: 目标文本键，支持点分隔，例如 'response.success'
        :param default: 目标语言文本不存在时的默认文本
        :param kwargs: 目标文本中的变量参数
        :return:
        """
        # 获取当前请求的语言
        current_lang = self.get_request_language()

        # 创建缓存键
        cache_key = self._create_cache_key(key, kwargs, current_lang)

        # 检查缓存（如果缓存键有效）
        if cache_key is not None and cache_key in self._cache:
            return self._cache[cache_key]

        # 首先尝试当前语言
        translation = self._get_translation_by_path(current_lang, key)

        # 如果当前语言找不到，尝试默认语言
        if translation is None and current_lang != settings.I18N_DEFAULT_LANGUAGE:
            translation = self._get_translation_by_path(settings.I18N_DEFAULT_LANGUAGE, key)

        # 如果还是找不到，处理特殊情况
        if translation is None:
            if key == 'error.language_not_found' or key.startswith('pydantic.'):
                # 特殊键处理
                result = default if key.startswith('pydantic.') else key
            else:
                result = default or key
        else:
            # 处理参数替换
            if kwargs:
                try:
                    parsed_kwargs = self._parse_kwargs_optimized(kwargs, current_lang)
                    result = translation.format(**parsed_kwargs)
                except (KeyError, ValueError):
                    # 参数缺失或格式错误时返回原文本
                    result = translation
                except TypeError:
                    # 类型错误时返回原文本
                    result = translation
            else:
                result = translation

        # 缓存结果（如果缓存键有效）
        if cache_key is not None:
            self._evict_cache_if_needed()
            self._cache[cache_key] = result

        return result

    def clear_cache(self):
        """清空翻译缓存"""
        self._cache.clear()
        # 清空 LRU 缓存
        self._path_cache.cache_clear()

    def set_language(self, language: str):
        """
        设置当前语言并清空相关缓存

        注意：这个方法主要用于测试或非web环境
        在web环境中，语言通过中间件的ContextVar自动管理

        :param language: 语言代码
        """
        if self.current_language != language:
            self.current_language = language
            self.clear_cache()


# 创建 i18n 单例
i18n = I18n()

# 创建翻译函数实例
t = i18n.t
