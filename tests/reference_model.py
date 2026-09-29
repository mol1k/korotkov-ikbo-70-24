"""Упрощённая модель хранилища для тестирования на основе модели.

Записи хранятся в словарях вида {id: {поле: значение}}. Проверок
типов и ссылок нет: тест сам знает, какие вызовы должны завершиться
ошибкой, и в упрощённую модель передаёт только корректные вызовы.
"""

COLUMNS = {
    "Client": ("time", "platform"),
    "Prompt": ("time", "argument", "client", "tags", "stage"),
    "Result": ("time", "result", "stage", "error", "prompt", "cache_hit"),
}
WINDOW_SECONDS = 7 * 60


class ReferenceModel:
    """Эталонное состояние хранилища."""

    def __init__(self):
        """Создать пустые таблицы."""
        self.tables = {name: {} for name in COLUMNS}

    def row(self, table, uid):
        """Вернуть запись в виде списка, как её возвращает сервер."""
        record = self.tables[table][uid]
        return [uid] + [record[column] for column in COLUMNS[table]]

    def rows(self, table):
        """Вернуть все записи таблицы."""
        return [self.row(table, uid) for uid in self.tables[table]]

    def create(self, table, fields):
        """Добавить запись; идентификаторы идут подряд с 1."""
        uid = len(self.tables[table]) + 1
        self.tables[table][uid] = {
            column: fields.get(column) for column in COLUMNS[table]
        }
        return self.row(table, uid)

    def update(self, table, uid, fields):
        """Изменить переданные поля записи."""
        self.tables[table][uid].update(fields)
        return self.row(table, uid)

    def recent_prompts(self, now):
        """Ожидаемый результат get_recent_prompts для момента now."""
        rows = []
        for prompt in self.tables["Prompt"].values():
            client = self.tables["Client"][prompt["client"]]
            moment = client["time"]
            recent = moment is not None and now - moment <= WINDOW_SECONDS
            platform = client["platform"] if recent else None
            row = [platform, prompt["argument"]]
            if row not in rows:
                rows.append(row)
        return rows
