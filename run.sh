#!/bin/sh
set -e
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"

usage() {
    echo "Использование: ./run.sh КОМАНДА"
    echo "  install  установить зависимости из requirements.txt"
    echo "  repl     интерактивный режим модели данных"
    echo "  demo     демонстрация модели (команды из examples/demo.txt)"
    echo "  lint     проверка кода flake8 (PEP8, имена, сложность)"
}

case "$1" in
    install) "$PYTHON" -m pip install -r requirements.txt ;;
    repl) "$PYTHON" -m src.repl ;;
    demo) "$PYTHON" -m src.repl < examples/demo.txt ;;
    lint) "$PYTHON" -m flake8 src tests ;;
    *) usage ;;
esac
