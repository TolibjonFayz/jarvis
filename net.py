"""Tarmoq: bu kompyuterda IPv6 ulanish osilib qoladi (DNS esa Google
manzillari uchun avval IPv6 beradi, urllib timeout'i yordam bermaydi).
IPv4 manzillarni oldinga qo'yamiz — IPv6 o'chirilmaydi, faqat tartib."""
import socket


def prefer_ipv4():
    if getattr(socket.getaddrinfo, "_ipv4_first", False):
        return
    orig = socket.getaddrinfo

    def getaddrinfo(*args, **kwargs):
        return sorted(orig(*args, **kwargs), key=lambda r: r[0] != socket.AF_INET)

    getaddrinfo._ipv4_first = True
    socket.getaddrinfo = getaddrinfo
