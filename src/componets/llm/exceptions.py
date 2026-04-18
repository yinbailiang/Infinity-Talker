from typing import Optional


class LLMError(Exception):
    """LLM 客户端基础异常"""
    pass


class LLMRequestError(LLMError):
    """LLM 请求失败的基类（可包含原始异常和 HTTP 状态码）"""
    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.status_code = status_code
        self.response_body = response_body


class LLMNetworkError(LLMRequestError):
    """网络层错误：连接失败、超时、DNS 解析等"""
    pass


class LLMHTTPError(LLMRequestError):
    """HTTP 响应状态码非 200 的错误（基类）"""
    pass


class LLMAuthError(LLMHTTPError):
    """认证失败：401 或 403"""
    pass


class LLMRateLimitError(LLMHTTPError):
    """速率限制：429"""
    pass


class LLMServerError(LLMHTTPError):
    """服务端错误：5xx"""
    pass


class LLMStreamError(LLMRequestError):
    """流式响应解析错误（JSON 解码、协议异常等）"""
    pass


def build_http_error(
    status_code: int,
    message: Optional[str] = None,
    original_error: Optional[Exception] = None,
    response_body: Optional[str] = None,
) -> LLMHTTPError:
    """
    根据 HTTP 状态码构建对应的 LLMHTTPError 子类实例。

    :param status_code: HTTP 状态码
    :param message: 自定义错误消息，若为 None 则生成默认消息
    :param original_error: 原始异常（可选）
    :param response_body: 响应体内容（可选）
    :return: 合适的异常实例
    """
    if message is None:
        message = f"HTTP {status_code}"

    if status_code in (401, 403):
        return LLMAuthError(
            message=message,
            status_code=status_code,
            original_error=original_error,
            response_body=response_body,
        )
    elif status_code == 429:
        return LLMRateLimitError(
            message=message,
            status_code=status_code,
            original_error=original_error,
            response_body=response_body,
        )
    elif 500 <= status_code < 600:
        return LLMServerError(
            message=message,
            status_code=status_code,
            original_error=original_error,
            response_body=response_body,
        )
    else:
        return LLMHTTPError(
            message=message,
            status_code=status_code,
            original_error=original_error,
            response_body=response_body,
        )