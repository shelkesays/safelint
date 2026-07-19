"""Flask app fixture - ``debug=True`` (SAFE905) + unvalidated ``request.json`` (SAFE907).

Flask does NOT get SAFE906 (no mass-assignment idiom), so there is no
mass-assignment fixture here.
"""

from flask import Flask, request


app = Flask(__name__)


def create():
    return save(request.json)


def create_validated():
    data = schema.validate(request.json)
    return save(data)


def run():
    app.run(debug=True)
