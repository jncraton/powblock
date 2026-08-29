all:

format:
	uvx black@24.1.0 server.py

lint:
	uvx black@24.1.0 --check server.py

clean:
	rm -rf *.db __pycache__
