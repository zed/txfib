#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
https://github.com/glenjamin/node-fib
"""
import decimal
import functools
import itertools
import math
import sys

from twisted.internet import reactor, defer, task, utils, threads
from twisted.python   import log
from twisted.web      import http, resource, server, static


class FibResource(resource.Resource):
    """Serve nth fibonacci number on /n request.

    Cancel computations on disconnect.
    """
    isLeaf = True
    def __init__(self, fib):
        resource.Resource.__init__(self)
        self.fib = fib

    def render_GET(self, request):
        try: n = int(request.postpath[0])
        except (IndexError, ValueError), e:
            request.setResponseCode(http.BAD_REQUEST)
            return str(e)
            
        d = defer.maybeDeferred(self.fib, n)
        d.addCallback(str).addCallback(request.write)
        d.addCallback(lambda _: request.finish())
        d.addErrback(self.fail_request, request)
        request.notifyFinish().addErrback(lambda _: d.cancel())
        return server.NOT_DONE_YET

    def fail_request(self, reason, request):
        if reason:
            if reason.check(defer.CancelledError):
                reason = None # discard
            else: # show page with stacktrace
                request.processingFailed(reason)


def gcd(a, b):
    """Return GCD (greatest common divisor) for positive integers a,b.

    >>> gcd(12, 15) == gcd(15, 12) == 3
    True
    >>> gcd(1, 100)
    1
    >>> gcd(3, 100)
    1
    >>> gcd(5, 100)
    5
    >>> gcd(10, 0)
    10
    """
    while b:
        a, b = b, a % b
    return a


def cooperator(iterable, n, yield_interval, callback):
    """
    - call next(iterable) `n` times
    - yield None every `yield_interval` iterations or more times
    - call callback with the result of the nth (last) iteration or None

    >>> import pprint
    >>> list(cooperator(range(1, 10), 5, 3, pprint.pprint))
    5
    [None, None, None, None, None]
    >>> list(cooperator(range(1, 10), 7, 3, pprint.pprint))
    7
    [None, None, None]
    """
    f = None
    yield_interval = gcd(max(n-1, 1), yield_interval)
    for f in itertools.islice(iterable, 0, n, yield_interval):
        yield None
    callback(f)


def gen2deferred(yield_interval=1):
    def gen_decorator(func):
        @functools.wraps(func)
        def wrapper(n):
            def stop_task(unused_deferred):
                try: t.stop()
                except task.TaskFailed: pass
            d = defer.Deferred(canceller=stop_task)
            t = task.cooperate(cooperator(func(n), n+1,
                                          yield_interval, d.callback))    
            return d
        return wrapper
    return gen_decorator


@gen2deferred(yield_interval=1000)
def iterfib(n=None, a=0, b=1):
    """Lazely generate fibonacci sequence.

    O(n) steps, O(n) in memory (to hold the result)

    NOTE: each step involves bignumbers so it is actually O(n) in time
    """
    while 1:
        yield a
        a, b = b, a+b


@gen2deferred(yield_interval=1)
def sicpfib(n):
    """Compute nth fibonacci number. Yielding None during computations.

    O(log(n)) steps, O(n) in memory (to hold the result)
    
    Function Fib(count)
        a ← 1
        b ← 0
        p ← 0
        q ← 1

        While count > 0 Do
            If Even(count) Then
                 p ← p² + q²
                 q ← 2pq + q²
                 count ← count ÷ 2
            Else
                 a ← bq + aq + ap
                 b ← bp + aq
                 count ← count - 1
            End If
        End While

        Return b
    End Function

    See http://stackoverflow.com/questions/1525521/nth-fibonacci-number-in-sublinear-time/1526036#1526036
    """
    a, b, p, q = 1, 0, 0, 1
    while n > 0:
        yield None
        if n % 2 == 0: # even
            oldp = p
            p = p*p + q*q
            q = 2*oldp*q + q*q
            n //= 2
        else:
            olda = a
            a = b*q + a*q + a*p
            b = b*p + olda*q
            n -= 1
    yield b


def _recfib(n):
    """
    >>> _recfib(10)
    55
    """
    if n == 0: return 0
    if n == 1: return 1
    return _recfib(n-2) + _recfib(n-1)


def recfib(n):
    """Unmodified blocking alg.

    NOTE: uninterruptable
    
    O(a**n) steps, O(a**n) memory in a thread
    """
    return threads.deferToThread(_recfib, n)


def memoize_deferred(func):
    """Unlimited cache for a function that returns deferred."""
    def setcache(value, cache, n):
        cache[n] = value
        return value

    cache = {}
    @functools.wraps(func)
    def wrapper(n):
        try: return defer.succeed(cache[n])
        except KeyError:
            d = func(n)
            d.addCallback(setcache, cache, n)
            return d
    return wrapper


@memoize_deferred
def memfib(n):
    """Return deferred nth fibonacci number.

    Famous recursive formula with unlimited memoization

    O(a**n) steps, O(a**n) memory
    """
    if n == 0: return defer.succeed(0)
    if n == 1: return defer.succeed(1)
    
    d = defer.gatherResults([task.deferLater(reactor, 0, memfib, n-2),
                             task.deferLater(reactor, 0, memfib, n-1)])
    return d.addCallback(sum)
    

def binet_decimal(n, precision=None):
    """Calculate nth fibonacci number using Binet's formula.

    O(1) steps, O(1) in memory

    NOTE: uninterruptable
    
    >>> map(binet_decimal, range(10))
    ['0', '1', '1', '2', '3', '5', '8', '13', '21', '34']
    """
    with decimal.localcontext() as cxt:
        if precision is not None:
            cxt.prec = precision
        with decimal.localcontext(cxt) as nested_cxt:
            nested_cxt.prec += 2  # increase prec. for intermediate results
            sqrt5 = decimal.Decimal(5).sqrt()
            f = ((1 + sqrt5) / 2)**n / sqrt5
        s = str(+f.to_integral()) # round to required precision
    return s
binetfib = binet_decimal


def ndigits_fibn(n):
    """Find number of decimal digits in fib(n)."""
    phi = (1 + math.sqrt(5)) / 2
    return int(n*math.log10(phi)-math.log10(5)/2)+1

def binetfib_exact(n):
    """Call binetfib() with calculated precision.

    O(1) *bigdecimal steps*, O(n) in memory
    """
    return utils.getProcessOutput(sys.executable,
        ['-c', """import fibonacci as f, sys
sys.stdout.write(f.binet_decimal({n}, f.ndigits_fibn({n})))""".format(n=n)])

# from twisted/internet/utils.py
# modified to kill child process on deferred.cancel()
def _callProtocolWithDeferred(protocol, executable, args, env, path, reactor=None):
    if reactor is None:
        from twisted.internet import reactor

    d = defer.Deferred(canceller=lambda d: p.transport.signalProcess('KILL'))
    p = protocol(d)
    reactor.spawnProcess(p, executable, (executable,)+tuple(args), env, path)
    return d
#HACK: patch t.i.utils
utils._callProtocolWithDeferred = _callProtocolWithDeferred
del _callProtocolWithDeferred

def getFibFactory():
    root = resource.Resource()

    html = '<!doctype html><html><body><ul>'
    for f in [iterfib, sicpfib, binetfib, binetfib_exact,
              memfib, recfib,
              ]:
        html += '<li><a href="/{f}/17">{f}</a>\n'.format(f=f.__name__)
        root.putChild(f.__name__, FibResource(f))
    root.putChild('', static.Data(html, 'text/html'))
    return server.Site(root)


def shutdown(reason, reactor, stopping=[]):
    """Stop the reactor."""
    if stopping: return
    stopping.append(True)
    if reason:
        log.msg(reason.value)
    reactor.callWhenRunning(reactor.stop)


portstr = "tcp:1597"

if __name__ == '__main__':
    import doctest; doctest.testmod()

    from twisted.internet import endpoints
    
    log.startLogging(sys.stdout)
    endpoint = endpoints.serverFromString(reactor, portstr)
    d = endpoint.listen(getFibFactory())
    d.addErrback(shutdown, reactor)
    reactor.run()
else: # twistd -ny
    from twisted.application import strports
    from twisted.application.service import Application
    
    application = Application("fibonacci")

    service = strports.service(portstr, getFibFactory())
    service.setServiceParent(application)
