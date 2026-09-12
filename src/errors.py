"""Исключения модели слоя работы с данными и протокола RPC."""


class ModelError(Exception):
    """Базовая ошибка модели слоя работы с данными."""


class ValidationError(ModelError):
    """Значение поля записи имеет недопустимый тип или отсутствует."""


class NotFoundError(ModelError):
    """Запись с указанным идентификатором не найдена."""


class ProtocolError(Exception):
    """Сообщение RPC не соответствует спецификации протокола."""
