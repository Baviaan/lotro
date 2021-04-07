import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.ssl_ import create_urllib3_context

# Force ECDHE because Lotro defaults to 1024bit DH
# and requests aborts the connection for weak keys
# Lotro has an RSA certificate
CIPHERS = (
        'ECDHE-RSA-AES256-GCM-SHA384'
)


class ECDHEAdapter(HTTPAdapter):
    """
    A TransportAdapter that specifies ECDHE in Requests.
    """
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=CIPHERS)
        kwargs['ssl_context'] = context
        return super(ECDHEAdapter, self).init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context(ciphers=CIPHERS)
        kwargs['ssl_context'] = context
        return super(ECDHEAdapter, self).proxy_manager_for(*args, **kwargs)
