all:

format:
	uvx black@24.1.0 server.py
	npx --yes prettier@3.6.2 --write *.html

lint:
	npx --yes prettier@3.6.2 --check *.html
	uvx black@24.1.0 --check server.py

clean:
	rm -rf *.db __pycache__
