"""PostgreSQL pool lifecycle."""


def pool_options(env):
    raise NotImplementedError


async def open_pool():
    raise NotImplementedError


async def close_pool(pool):
    raise NotImplementedError
