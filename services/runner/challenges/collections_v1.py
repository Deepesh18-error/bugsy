"""Trusted black-box tests. Submission code executes only in the jail."""

async def oop_stack_push_size(s):
    await s.construct('Stack')
    assert await s.call('size') == 0
    await s.call('push', 7)
    await s.call('push', 0)
    assert await s.call('size') == 2

async def oop_stack_pop_order(s):
    await s.construct('Stack')
    for value in (3, 8, -2):
        await s.call('push', value)
    for expected in (-2, 8, 3):
        value = await s.call('pop')
        assert type(value) is int and value == expected
    assert await s.call('size') == 0

async def oop_stack_peek_preserves(s):
    await s.construct('Stack')
    await s.call('push', 4)
    await s.call('push', 9)
    assert await s.call('peek') == 9
    assert await s.call('peek') == 9
    assert await s.call('size') == 2

async def oop_stack_empty_reuse(s):
    await s.construct('Stack')
    assert await s.call('pop') is None
    assert await s.call('peek') is None
    for value in (0, -5, 0):
        await s.call('push', value)
    for expected in (0, -5, 0):
        assert await s.call('pop') == expected
    assert await s.call('pop') is None
    await s.call('push', 21)
    assert await s.call('peek') == 21
    assert await s.call('size') == 1

async def backend_wallet_deposit_balance(s):
    await s.construct('Wallet')
    assert await s.read('balance') == 0
    assert await s.call('deposit', 125) is True
    assert await s.call('deposit', 75) is True
    assert await s.read('balance') == 200
    assert await s.read('history') == [125, 75]

async def backend_wallet_withdraw_bounds(s):
    await s.construct('Wallet')
    assert await s.call('deposit', 100) is True
    assert await s.call('withdraw', 101) is False
    assert await s.read('balance') == 100
    assert await s.read('history') == [100]
    assert await s.call('withdraw', 100) is True
    assert await s.read('balance') == 0
    assert await s.read('history') == [100, -100]
    assert await s.call('withdraw', 1) is False

async def backend_wallet_statement_copy(s):
    await s.construct('Wallet')
    await s.call('deposit', 37)
    assert await s.call('statement') == [37]
    # This operation mutates the returned list *inside* the jail, not a JSON
    # copy in the supervisor, so accidental aliasing is actually detected.
    assert await s.call('statement_is_copy') is True
    assert await s.read('history') == [37]

async def backend_wallet_invalid_amounts(s):
    await s.construct('Wallet')
    await s.call('deposit', 50)
    for amount in (0, -1, True, False, 1.5, '10', None):
        assert await s.call('deposit', amount) is False
        assert await s.call('withdraw', amount) is False
    assert await s.read('balance') == 50
    assert await s.call('statement') == [50]
