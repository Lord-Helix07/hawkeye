from mangum import Mangum
from website.api import app

handler = Mangum(app, api_gateway_base_path="/default/HawkeyeBackendContainer")