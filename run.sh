#!/bin/sh
set -e
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-9090}"

usage() {
    echo "Использование: ./run.sh КОМАНДА"
    echo "  install   установить зависимости из requirements.txt"
    echo "  repl      интерактивный режим модели данных"
    echo "  demo      демонстрация модели (команды из examples/demo.txt)"
    echo "  server    запустить сервер RPC на \$HOST:\$PORT"
    echo "  client    REPL через клиент RPC к серверу \$HOST:\$PORT"
    echo "  demo-rpc  запустить сервер и выполнить демонстрацию через RPC"
    echo "  test      тесты MBT (hypothesis) с отчётом о покрытии (coverage)"
    echo "  lint      проверка кода flake8 (PEP8, имена, сложность)"
    echo "Переменные окружения: PYTHON, HOST (127.0.0.1), PORT (9090)."
}

demo_rpc() {
    "$PYTHON" -m src.server --host "$HOST" --port "$PORT" &
    server_pid=$!
    trap 'kill "$server_pid" 2>/dev/null' EXIT
    sleep 1
    "$PYTHON" -m src.repl --remote "$HOST:$PORT" < examples/demo.txt
    sleep 1
}

case "$1" in
    install) "$PYTHON" -m pip install -r requirements.txt ;;
    repl) "$PYTHON" -m src.repl ;;
    demo) "$PYTHON" -m src.repl < examples/demo.txt ;;
    server) "$PYTHON" -m src.server --host "$HOST" --port "$PORT" ;;
    client) "$PYTHON" -m src.repl --remote "$HOST:$PORT" ;;
    demo-rpc) demo_rpc ;;
    test)
        "$PYTHON" -m coverage run -m unittest discover -s tests -t . -v
        "$PYTHON" -m coverage report
        ;;
    lint) "$PYTHON" -m flake8 src tests ;;
    *) usage ;;
esac
