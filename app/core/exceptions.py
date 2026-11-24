from fastapi import status


class AppError(Exception):
    """业务异常基类，由全局异常处理器统一转换为响应。"""

    def __init__(
        self,
        message: str,
        *,
        code: int = 40000,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class BadRequestError(AppError):
    def __init__(self, message: str = "请求参数有误") -> None:
        super().__init__(message, code=40000, status_code=status.HTTP_400_BAD_REQUEST)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "未登录或登录已过期") -> None:
        super().__init__(message, code=40100, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(AppError):
    def __init__(self, message: str = "没有权限执行该操作") -> None:
        super().__init__(message, code=40300, status_code=status.HTTP_403_FORBIDDEN)


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(message, code=40400, status_code=status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    def __init__(self, message: str = "资源已存在") -> None:
        super().__init__(message, code=40900, status_code=status.HTTP_409_CONFLICT)
