"""VWSHub 0.7 entry point. Use a production WSGI server for deployment."""
import os
from hub.core import create_app

app=create_app()

if __name__=="__main__":
    app.run(host=os.getenv("HOST","127.0.0.1"),port=int(os.getenv("PORT","5000")),threaded=True,debug=False)
