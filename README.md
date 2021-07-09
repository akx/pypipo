# pypipo

Proof of concept simple PyPI pull-through proxy. Absolutely not usable for production just yet.

## usage

### run server

* install requirements
* ` uvicorn pypipo:app --port 8101`

### use server

```
pip install --index-url=http://localhost:8101/simple/ black
```