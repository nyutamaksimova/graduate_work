from sqlalchemy import inspect


def serialize(model):
    return {column.key: getattr(model, column.key) for column in inspect(model).mapper.column_attrs}
