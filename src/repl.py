"""Интерактивный режим (REPL) для модели слоя работы с данными.

Команда вводится как вызов функции модели, аргументы записываются
литералами Python. Имя now в аргументах означает текущее Unix-время,
к нему можно прибавлять и вычитать целые числа::

    model> create_client(time=now - 60, platform="linux")
    model> update_client(1, platform="macos")
    model> get_recent_prompts()

Служебные команды: help, now, exit, quit.
"""
import argparse
import ast
import inspect
import sys
import time

from src import model
from src.errors import ModelError, ProtocolError

PROMPT = "model> "
EXIT_COMMANDS = ("exit", "quit")
COMMANDS = tuple(function.__name__ for function in model.API)


def _evaluate(node, now):
    """Вычислить значение аргумента: литерал, now или сумму/разность."""
    if isinstance(node, ast.Name) and node.id == "now":
        return now
    if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub)):
        left = _evaluate(node.left, now)
        right = _evaluate(node.right, now)
        if isinstance(node.op, ast.Add):
            return left + right
        return left - right
    return ast.literal_eval(node)


def parse_command(line, now):
    """Разобрать строку вида имя(аргументы).

    :return: кортеж (имя, позиционные аргументы, именованные аргументы).
    :raises SyntaxError, ValueError: если строка не является вызовом.
    """
    tree = ast.parse(line.strip(), mode="eval").body
    if isinstance(tree, ast.Name):
        return tree.id, [], {}
    if not isinstance(tree, ast.Call) or not isinstance(tree.func, ast.Name):
        raise ValueError("ожидается вызов функции: имя(аргументы)")
    args = [_evaluate(arg, now) for arg in tree.args]
    kwargs = {item.arg: _evaluate(item.value, now) for item in tree.keywords}
    return tree.func.id, args, kwargs


def format_result(result):
    """Преобразовать результат вызова в текст для вывода."""
    if isinstance(result, list) and not result:
        return "(нет записей)"
    if isinstance(result, list) and all(
            isinstance(row, list) for row in result):
        return "\n".join(repr(row) for row in result)
    return repr(result)


def help_text():
    """Вернуть справку по командам REPL."""
    lines = ["Функции модели:"]
    for function in model.API:
        signature = inspect.signature(function)
        summary = inspect.getdoc(function).splitlines()[0]
        lines.append(f"  {function.__name__}{signature}")
        lines.append(f"      {summary}")
    lines.append("Служебные команды: help, now, exit, quit.")
    lines.append("KEEP означает «не менять поле», now — текущее время.")
    return "\n".join(lines)


def execute(backend, line):
    """Выполнить одну команду REPL и вернуть текст ответа.

    :param backend: объект с функциями модели (модуль model или
        клиент RPC).
    """
    command = line.strip()
    if not command:
        return ""
    if command == "help":
        return help_text()
    if command == "now":
        return str(int(time.time()))
    try:
        name, args, kwargs = parse_command(command, int(time.time()))
        if name not in COMMANDS:
            raise ValueError(f"неизвестная команда {name}, см. help")
        result = getattr(backend, name)(*args, **kwargs)
    except (ModelError, ProtocolError) as error:
        return f"Ошибка {type(error).__name__}: {error}"
    except (SyntaxError, ValueError, TypeError) as error:
        return f"Ошибка ввода: {error}"
    except ConnectionError as error:
        return f"Ошибка соединения: {error}"
    return format_result(result)


def run(backend, echo=False):
    """Запустить цикл чтения и выполнения команд.

    :param echo: печатать введённую команду (при вводе из файла).
    """
    print("REPL модели данных. Справка: help, выход: exit.")
    while True:
        try:
            line = input(PROMPT)
        except EOFError:
            print()
            break
        if echo:
            print(line)
        if line.strip() in EXIT_COMMANDS:
            break
        output = execute(backend, line)
        if output:
            print(output)


def main():
    """Точка входа: python -m src.repl."""
    parser = argparse.ArgumentParser(
        description="REPL для модели слоя работы с данными")
    parser.parse_args()
    run(model, echo=not sys.stdin.isatty())


if __name__ == "__main__":
    main()
