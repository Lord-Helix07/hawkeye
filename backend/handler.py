from mangum import Mangum
from website.api import app

handler = Mangum(app)