#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.conf import settings

# 使用 ContextVar 来存储每个请求的语言设置
current_language_context: ContextVar[str] = ContextVar('current_language', default=settings.I18N_DEFAULT_LANGUAGE)


class I18nMiddleware(BaseHTTPMiddleware):
    """国际化中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求并设置国际化语言

        :param request: FastAPI 请求对象
        :param call_next: 下一个中间件或路由处理函数
        :return:
        """
        language = self.get_current_language(request)

        # 设置当前请求的语言上下文
        current_language_context.set(language)

        response = await call_next(request)

        return response

    def get_current_language(self, request: Request) -> str:
        """
        获取当前请求的语言偏好

        :param request: FastAPI 请求对象
        :return: 语言代码
        """
        # 优先级：URL参数 > Header > 默认语言

        # 1. 检查 URL 参数
        lang_from_query = request.query_params.get('lang')
        if lang_from_query:
            mapped_lang = self._map_language(lang_from_query)
            if mapped_lang:
                return mapped_lang

        # 2. 检查 Accept-Language 头
        accept_language = request.headers.get('Accept-Language', '')
        if accept_language:
            # 解析 Accept-Language 头，格式如: "zh-CN,zh;q=0.9,en;q=0.8"
            languages = []
            for lang_item in accept_language.split(','):
                lang_code = lang_item.split(';')[0].strip()
                if lang_code:
                    languages.append(lang_code)

            if languages:
                mapped_lang = self._map_language(languages[0])
                if mapped_lang:
                    return mapped_lang

        # 3. 返回默认语言
        return settings.I18N_DEFAULT_LANGUAGE

    def _map_language(self, lang: str) -> str:
        """
        映射语言代码到标准格式

        :param lang: 原始语言代码
        :return: 标准语言代码
        """
        if not lang:
            return settings.I18N_DEFAULT_LANGUAGE

        lang = lang.lower().strip()

        # 语言映射表
        lang_mapping = {
            'zh': 'zh-CN',
            'zh-cn': 'zh-CN',
            'zh-hans': 'zh-CN',
            'en': 'en-US',
            'en-us': 'en-US',
        }

        return lang_mapping.get(lang, settings.I18N_DEFAULT_LANGUAGE)


def get_current_language() -> str:
    """
    获取当前请求的语言设置

    :return: 当前语言代码
    """
    return current_language_context.get()
