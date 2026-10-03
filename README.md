Прототип веб-приложения с RPC на основе TCP
===========================================

Практическая работа №1, вариант 7.
Дисциплина «Прикладная разработка серверных частей веб-приложений на языке Питон».

Коротков Дмитрий Максимович, группа ИКБО-70-24.


1. Общее описание
-----------------

Прототип веб-приложения хранит данные только в памяти, на диск ничего
не сохраняется. Схема данных состоит из трёх сущностей: Client, Prompt
и Result.

Работа выполнена в три этапа:

- этап 1: модель слоя доступа к данным и интерактивный режим (REPL);
- этап 2: удалённый вызов процедур (RPC) на основе TCP - сервер с
  журналом запросов и ответов и клиент в виде класса;
- этап 3: тестирование RPC на основе модели (MBT) с помощью hypothesis
  и отчёт о покрытии кода по ветвям (coverage).

Требуется Python 3.10 или новее.

Состав репозитория:

- src/model.py - модель слоя работы с данными (10 функций);
- src/errors.py - исключения;
- src/repl.py - интерактивный режим, локальный и через RPC;
- src/protocol.py - формат сообщений RPC;
- src/server.py - сервер RPC на основе TCP с журналом;
- src/client.py - клиент RPC (класс RpcClient);
- tests/test_rpc_state_machine.py - тесты MBT;
- tests/reference_model.py - упрощённая модель для MBT;
- examples/demo.txt - сценарий демонстрации;
- run.sh - скрипт запуска;
- requirements.txt - зависимости;
- .flake8, .coveragerc - настройки проверки кода и замера покрытия.


2. Схема данных
---------------

Client: id (int), time (int), platform (str).

Prompt: id (int), time (int), argument (str), client (int), tags (str),
stage (str). Поле client ссылается на Client.id.

Result: id (int), time (int), result (str), stage (str), error (str),
prompt (int), cache_hit (int). Поле prompt ссылается на Prompt.id.

У клиента может быть ноль или несколько запросов (Prompt), у запроса -
ноль или несколько результатов (Result).

Каждая запись хранится в памяти списком значений в порядке столбцов,
например [1, 1791233465, 'linux'] для Client. Таблица - список таких
записей.

Обязательные поля: id, Prompt.client и Result.prompt. Остальные поля
могут иметь значение None. Поле time - Unix-время в секундах.
Идентификатор id назначается автоматически: 1, 2, 3 и так далее.


3. Функции модели
-----------------

Все функции находятся в src/model.py. Функции создания и изменения
возвращают итоговую запись, функции получения - копии всех записей
таблицы.

Сигнатуры функций:

    create_client(time=None, platform=None)
    get_clients()
    update_client(uid, time=KEEP, platform=KEEP)

    create_prompt(time=None, argument=None, client=None, tags=None,
                  stage=None)
    get_prompts()
    update_prompt(uid, time=KEEP, argument=KEEP, client=KEEP,
                  tags=KEEP, stage=KEEP)

    create_result(time=None, result=None, stage=None, error=None,
                  prompt=None, cache_hit=None)
    get_results()
    update_result(uid, time=KEEP, result=KEEP, stage=KEEP, error=KEEP,
                  prompt=KEEP, cache_hit=KEEP)

    get_recent_prompts(now=None)

В функциях изменения значение KEEP (по умолчанию) означает «оставить
поле без изменений», поэтому передаются только изменяемые поля,
например update_client(1, platform="macos"). Значение None очищает
поле.

Функция get_recent_prompts реализует формулу реляционной алгебры
варианта:

    pi[C.platform, P.argument](
        (sigma[C.time >= now - 7 min] C)
        правое внешнее соединение [C.id = P.client]
        P
    )

Порядок вычисления:

- выборка sigma отбирает клиентов, у которых time >= now - 420 секунд;
- правое внешнее соединение с Prompt по условию C.id = P.client
  сохраняет все записи Prompt; если клиент записи не попал в выборку,
  его поля равны None;
- проекция pi оставляет столбцы platform и argument и удаляет
  повторяющиеся строки, как принято в реляционной алгебре.

Результат - список строк [platform, argument]. Параметр now
(Unix-время) по умолчанию равен текущему времени.

Ошибки модели:

- ValidationError - неверный тип поля или пустое обязательное поле;
- NotFoundError - нет записи с указанным uid или нет записи, на
  которую ссылается внешний ключ.

При ошибке хранилище не изменяется.


4. Протокол RPC
---------------

Сервер (src/server.py) принимает TCP-соединения. В одном соединении
можно передавать любое число запросов подряд. Каждой из 10 функций
модели соответствует код операции.

Структура запроса (таблица 7 варианта):

    смещение 0, 1 байт  - код операции
    смещение 1, 5 байт  - размер тела запроса
    смещение 6          - тело в формате XML

Структура ответа:

    смещение 0, 2 байта - код операции
    смещение 2, 4 байта - размер тела ответа
    смещение 6          - тело в формате XML

Числа в заголовках записываются от младшего байта к старшему
(little-endian). Тело кодируется в UTF-8.

Коды операций:

    1 - create_client      6 - update_prompt
    2 - get_clients        7 - create_result
    3 - update_client      8 - get_results
    4 - create_prompt      9 - update_result
    5 - get_prompts       10 - get_recent_prompts

Код операции в ответе занимает 2 байта: младший байт повторяет код
операции запроса, старший байт содержит статус выполнения:

    0 - успешно
    1 - неверный тип поля  (на клиенте ValidationError)
    2 - запись не найдена  (на клиенте NotFoundError)
    3 - ошибка протокола   (на клиенте ProtocolError)

Ошибка протокола возвращается при неизвестном коде операции,
некорректном XML, неизвестных аргументах функции и теле запроса
больше 1 МиБ. В последнем случае сервер после ответа закрывает
соединение.

Значения в теле кодируются элементами none, int, str и list (список
может содержать любые из них). Аргументы передаются по именам
параметров функции модели. Пример тела запроса:

    <request>
      <arg name="time"><int>1791233598</int></arg>
      <arg name="platform"><str>linux</str></arg>
    </request>

Успешный ответ содержит одно значение, ответ с ошибкой - текст:

    <response>
      <list><int>1</int><int>1791233598</int><str>linux</str></list>
    </response>

    <response><error>Client: запись с id=99 не найдена</error></response>

Строки не должны содержать управляющих символов, недопустимых в
XML 1.0 (кроме табуляции и перевода строки). Такие строки клиент
отклоняет с ProtocolError до отправки.

Пример в байтах: вызов create_client(time=1791233598, platform="linux"),
тело 106 байт (0x6A):

    01 6a 00 00 00 00 <request>...</request>
    01                 код операции 1
       6a 00 00 00 00  размер тела 106, младший байт первый

Ответ: код 1, статус 0, тело 83 байта (0x53):

    01 00 53 00 00 00 <response>...</response>
    01 00              код операции 1 и статус 0
          53 00 00 00  размер тела 83

Ответ с ошибкой на update_client (код 3, статус 2):

    03 02 55 00 00 00 <response><error>...</error></response>

Сервер записывает в стандартный вывод подключения, все запросы (код,
имя функции, размер, тело) и все ответы (код, статус, размер, тело).


5. Клиент RPC
-------------

Класс RpcClient (src/client.py) подключается к серверу. Его методы
называются так же, как функции модели, и возвращают тот же результат.
Ошибки сервера возбуждаются на клиенте исключениями ValidationError,
NotFoundError и ProtocolError.

Пример использования:

    from src.client import RpcClient

    with RpcClient("127.0.0.1", 9090) as client:
        client.create_client(time=1791233598, platform="linux")
        client.update_client(1, platform="macos")
        print(client.get_recent_prompts())

Методы update_client, update_prompt и update_result принимают
идентификатор и только изменяемые поля именованными аргументами.
Метод send_raw(payload) отправляет готовые байты запроса и возвращает
кортеж (код, статус, тело) - для отладки протокола.


6. Настройки
------------

- окно выборки get_recent_prompts: 7 минут (RECENT_WINDOW_SECONDS в
  src/model.py);
- адрес сервера: 127.0.0.1 (ключ --host, переменная HOST для run.sh);
- порт сервера: 9090 (ключ --port, переменная PORT для run.sh);
- наибольший размер тела запроса: 1 МиБ (MAX_BODY_SIZE в
  src/protocol.py);
- тайм-аут клиента: 10 секунд (аргумент timeout у RpcClient).


7. Сборка, запуск и тесты
-------------------------

Сборка не требуется. Установка зависимостей (hypothesis, coverage,
flake8, pep8-naming):

    ./run.sh install

Команды run.sh:

    ./run.sh repl       интерактивный режим модели
    ./run.sh demo       демонстрация: команды из examples/demo.txt
    ./run.sh server     сервер RPC (журнал в стандартный вывод)
    ./run.sh client     REPL через клиент RPC (сервер должен работать)
    ./run.sh demo-rpc   запуск сервера и демонстрация через RPC
    ./run.sh test       тесты MBT с замером покрытия и отчётом
    ./run.sh lint       проверка кода flake8

Адрес и порт задаются переменными, например PORT=9191 ./run.sh server.

Без run.sh (например, в Windows) из корня репозитория:

    python -m src.repl
    python -m src.server --port 9090
    python -m src.repl --remote 127.0.0.1:9090
    python -m coverage run -m unittest discover -s tests -t . -v
    python -m coverage report
    python -m flake8 src tests

В интерактивном режиме команда вводится как вызов функции модели с
аргументами-литералами Python. Имя now в аргументах означает текущее
Unix-время, к нему можно прибавлять и вычитать числа, например
create_client(time=now - 60). Служебные команды: help (список
функций), now, exit.


8. Тестирование на основе модели
--------------------------------

Тесты находятся в папке tests и используют класс RuleBasedStateMachine
из библиотеки hypothesis.

Сложная система - сервер RPC (src/server.py и модель src/model.py). Он
запускается в отдельном потоке на свободном порту, тест работает с ним
только через клиент RpcClient.

Упрощённая модель - tests/reference_model.py: таблицы хранятся в
словарях вида {id: {поле: значение}}, проверок типов и ссылок нет.

hypothesis генерирует случайные последовательности правил (до 40
шагов, 200 сценариев) и выполняет каждое правило одновременно над
сервером и над упрощённой моделью. После каждого шага инвариант
tables_match_reference сравнивает результаты get_clients, get_prompts
и get_results с состоянием упрощённой модели. При расхождении
hypothesis сокращает сценарий до минимального и печатает его.

Что проверяют правила:

- create_client, create_prompt, create_result - созданная запись
  совпадает с моделью;
- update_client, update_prompt, update_result - изменение любых
  наборов полей, перенос Prompt и Result к другой родительской записи;
- get_recent_prompts, get_recent_prompts_at_current_time,
  create_duplicate_prompt - выборка по формуле совпадает с моделью для
  разных моментов now и для текущего времени, повторяющиеся строки
  удаляются;
- правила с неверными типами полей, неверным id, неверным now и без
  обязательных полей - ValidationError, состояние не меняется;
- правила со ссылками на несуществующие записи - NotFoundError;
- send_unsupported_value, send_string_invalid_in_xml - ProtocolError
  на клиенте до отправки;
- send_unknown_operation, send_malformed_xml,
  send_bad_request_structure - ответ со статусом 3 (ошибка протокола);
- send_oversized_request, send_truncated_request - сервер закрывает
  соединение при слишком большом или неполном запросе.

Все 10 методов RPC и все ветви кода серверной и клиентской частей
покрываются только тестами, сгенерированными hypothesis. Покрытие
измеряется по ветвям (branch = True в .coveragerc). В замер не входят
src/repl.py (интерфейс командной строки) и функции main запуска из
командной строки.

Отчёт о покрытии кода тестами на основе ветвей (./run.sh test):

    Name              Stmts   Miss Branch BrPart  Cover   Missing
    -------------------------------------------------------------
    src/__init__.py       0      0      0      0   100%
    src/client.py        50      0      2      0   100%
    src/errors.py         4      0      0      0   100%
    src/model.py         85      0     22      0   100%
    src/protocol.py     114      0     18      0   100%
    src/server.py        68      0      8      0   100%
    -------------------------------------------------------------
    TOTAL               321      0     50      0   100%

Проверка оформления кода: ./run.sh lint запускает flake8 с плагином
pep8-naming (настройки в .flake8) - стиль и имена по PEP8, длина строк
не более 79 символов, цикломатическая сложность функций не более 5.


9. Примеры использования
------------------------

Модель в интерактивном режиме, вывод ./run.sh demo. Показаны все
функции модели и обработка ошибок:

    model> get_clients()
    (нет записей)
    model> create_client(time=now - 60, platform="linux")
    [1, 1791233465, 'linux']
    model> create_client(time=now - 3600, platform="windows")
    [2, 1791229925, 'windows']
    model> create_client(time=now - 120)
    [3, 1791233405, None]
    model> create_client(time="вчера", platform="linux")
    Ошибка ValidationError: поле time: ожидается int, получено str
    model> create_client(platform=42)
    Ошибка ValidationError: поле platform: ожидается str, получено int
    model> get_clients()
    [1, 1791233465, 'linux']
    [2, 1791229925, 'windows']
    [3, 1791233405, None]
    model> update_client(3, platform="macos")
    [3, 1791233405, 'macos']
    model> update_client(1, time=now - 30)
    [1, 1791233495, 'linux']
    model> update_client(99, platform="android")
    Ошибка NotFoundError: Client: запись с id=99 не найдена
    model> update_client("1", platform="android")
    Ошибка ValidationError: поле id: ожидается int, получено str
    model> update_client(1, time=1.5)
    Ошибка ValidationError: поле time: ожидается int, получено float
    model> get_clients()
    [1, 1791233495, 'linux']
    [2, 1791229925, 'windows']
    [3, 1791233405, 'macos']
    model> create_prompt(time=now, argument="hi", client=1, tags="a", stage="new")
    [1, 1791233525, 'hi', 1, 'a', 'new']
    model> create_prompt(time=now, argument="bye", client=2, stage="new")
    [2, 1791233525, 'bye', 2, None, 'new']
    model> create_prompt(time=now, argument="ping", client=3)
    [3, 1791233525, 'ping', 3, None, None]
    model> create_prompt(time=now, argument="hi", client=1, stage="retry")
    [4, 1791233525, 'hi', 1, None, 'retry']
    model> create_prompt(argument="lost", client=99)
    Ошибка NotFoundError: Client: запись с id=99 не найдена
    model> create_prompt(argument="no client")
    Ошибка ValidationError: поле client: ожидается int, получено NoneType
    model> create_prompt(argument=["list"], client=1)
    Ошибка ValidationError: поле argument: ожидается str, получено list
    model> get_prompts()
    [1, 1791233525, 'hi', 1, 'a', 'new']
    [2, 1791233525, 'bye', 2, None, 'new']
    [3, 1791233525, 'ping', 3, None, None]
    [4, 1791233525, 'hi', 1, None, 'retry']
    model> update_prompt(2, stage="done", tags="b")
    [2, 1791233525, 'bye', 2, 'b', 'done']
    model> update_prompt(2, client=99)
    Ошибка NotFoundError: Client: запись с id=99 не найдена
    model> update_prompt(10, stage="done")
    Ошибка NotFoundError: Prompt: запись с id=10 не найдена
    model> get_prompts()
    [1, 1791233525, 'hi', 1, 'a', 'new']
    [2, 1791233525, 'bye', 2, 'b', 'done']
    [3, 1791233525, 'ping', 3, None, None]
    [4, 1791233525, 'hi', 1, None, 'retry']
    model> create_result(time=now, result="ok", prompt=1, cache_hit=0)
    [1, 1791233525, 'ok', None, None, 1, 0]
    model> create_result(time=now, error="timeout", prompt=2, cache_hit=1)
    [2, 1791233525, None, None, 'timeout', 2, 1]
    model> create_result(result="orphan", prompt=99)
    Ошибка NotFoundError: Prompt: запись с id=99 не найдена
    model> create_result(result="bad", prompt=1, cache_hit="yes")
    Ошибка ValidationError: поле cache_hit: ожидается int, получено str
    model> get_results()
    [1, 1791233525, 'ok', None, None, 1, 0]
    [2, 1791233525, None, None, 'timeout', 2, 1]
    model> update_result(2, error=None, result="pong", stage="done")
    [2, 1791233525, 'pong', 'done', None, 2, 1]
    model> update_result(1, prompt=99)
    Ошибка NotFoundError: Prompt: запись с id=99 не найдена
    model> update_result(5, stage="done")
    Ошибка NotFoundError: Result: запись с id=5 не найдена
    model> get_results()
    [1, 1791233525, 'ok', None, None, 1, 0]
    [2, 1791233525, 'pong', 'done', None, 2, 1]
    model> get_recent_prompts()
    ['linux', 'hi']
    [None, 'bye']
    ['macos', 'ping']
    model> get_recent_prompts(now=now + 600)
    [None, 'hi']
    [None, 'bye']
    [None, 'ping']
    model> get_recent_prompts(now="сейчас")
    Ошибка ValidationError: поле now: ожидается int, получено str
    model> get_recent_prompts
    ['linux', 'hi']
    [None, 'bye']
    ['macos', 'ping']
    model> delete_client(1)
    Ошибка ввода: неизвестная команда delete_client, см. help
    model> create_client(time=now - 60
    Ошибка ввода: '(' was never closed (<unknown>, line 1)
    model> exit

В последнем вызове get_recent_prompts() строка [None, 'bye'] получена
правым внешним соединением: клиент 2 был активен час назад и не попал
в выборку sigma, но его запрос сохранился. Запросы 1 и 4 дают
одинаковую строку ['linux', 'hi'], проекция оставила одну.

Удалённый вызов через клиент RPC: ./run.sh demo-rpc выполняет тот же
сценарий через RpcClient, все результаты совпадают с локальными.
Отличие одно: значение 1.5 типа float не поддерживается протоколом и
отклоняется клиентом до отправки. Фрагмент вывода клиента:

    rpc> get_clients()
    (нет записей)
    rpc> create_client(time=now - 60, platform="linux")
    [1, 1791234323, 'linux']
    rpc> create_client(time=now - 3600, platform="windows")
    [2, 1791230783, 'windows']
    rpc> create_client(time=now - 120)
    [3, 1791234263, None]
    rpc> create_client(time="вчера", platform="linux")
    Ошибка ValidationError: поле time: ожидается int, получено str
    rpc> create_client(platform=42)
    Ошибка ValidationError: поле platform: ожидается str, получено int
    ...
    rpc> update_client(1, time=1.5)
    Ошибка ProtocolError: тип float не поддерживается протоколом
    ...
    rpc> get_recent_prompts()
    ['linux', 'hi']
    [None, 'bye']
    ['macos', 'ping']

Фрагмент журнала сервера для тех же вызовов (длинные строки
перенесены):

    запрос: код=2 (get_clients) размер=11 тело=<request />
    ответ: код=2 статус=0 размер=29 тело=<response><list /></response>
    запрос: код=1 (create_client) размер=106 тело=<request><arg
        name="time"><int>1791234323</int></arg><arg
        name="platform"><str>linux</str></arg></request>
    ответ: код=1 статус=0 размер=83 тело=<response><list><int>1</int><int>17
        91234323</int><str>linux</str></list></response>
    запрос: код=1 (create_client) размер=108 тело=<request><arg
        name="time"><int>1791230783</int></arg><arg
        name="platform"><str>windows</str></arg></request>
    ответ: код=1 статус=0 размер=85 тело=<response><list><int>2</int><int>17
        91230783</int><str>windows</str></list></response>
    ...
    запрос: код=3 (update_client) размер=99 тело=<request><arg
        name="uid"><int>99</int></arg><arg
        name="platform"><str>android</str></arg></request>
    ответ: код=3 статус=2 размер=85 тело=<response><error>Client: запись с
        id=99 не найдена</error></response>
