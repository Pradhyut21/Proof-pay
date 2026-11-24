# Thin wrapper over run.sh (Linux, macOS, WSL). Windows PowerShell: use .\run.ps1.
.PHONY: bootstrap check fmt smoke dataset audit reproduce api web e2e
bootstrap check fmt smoke dataset audit reproduce api web e2e:
	./run.sh $@
