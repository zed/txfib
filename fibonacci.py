#!/usr/bin/env python
"""
https://github.com/glenjamin/node-fib
"""
import decimal
import itertools

from twisted.internet       import reactor, defer, task, threads
from twisted.python         import log
from twisted.web            import http, resource, server

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
            
        d = self.fib(n)
        d.addCallback(str).addCallback(request.write)
        d.addCallback(lambda _: request.finish())
        d.addErrback(defer.logError)
        request.notifyFinish().addErrback(lambda _: d.cancel())
        return server.NOT_DONE_YET


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

def fibgen(a=0, b=1):
    """Lazely generate fibonacci sequence.

    >>> list(itertools.islice(fibgen(), 10))
    [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    """
    while 1:
        yield a
        a, b = b, a+b

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

def iterfib(n):
    """Return deferred n-th fibonacci number in a non-blocking manner.

    """    
    d = defer.Deferred(canceller=lambda _: t.stop())
    t = task.cooperate(cooperator(fibgen(), n+1, 1000, d.callback))    
    return d


def binet_decimal(n, precision=None):
    """
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
        s = str(+f.to_integral()) # get required precision
    return s

def test_binet_precision():
    for n in range(10)+[10000]:
        bd = binet_decimal(n)
        fi = str(next(itertools.islice(fibgen(), n, n+1)))
        assert bd == fi, (n, bd, fi)

def binetfib(n, precision=None):
    """Calculate nth fibonacci number using Binet's formula."""
    return threads.deferToThread(binet_decimal, n, precision)

if __name__ == '__main__':
    import os
    with open('f.pid', 'w') as f:
        f.write(str(os.getpid()))
    
    import doctest; doctest.testmod()

    import sys
    log.startLogging(sys.stdout)
    root = resource.Resource()
    root.putChild("iterfib", FibResource(iterfib))
    root.putChild("binetfib", FibResource(binetfib))
    reactor.listenTCP(8880, server.Site(root))
    reactor.run()
