# The Python project lives in pipeline/ (docs/adr/0001). The root delegates,
# so `make verify` from a fresh clone runs exactly the gate CI runs
# (CI-CD-STANDARD §9, CICD-27).
.PHONY: verify

verify:
	$(MAKE) -C pipeline verify
