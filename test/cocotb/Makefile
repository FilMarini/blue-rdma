ROOT_DIR = $(abspath ../../)
include $(ROOT_DIR)/Makefile.base
ROOT_DIR = $(abspath ../../)
SRC_DIR = $(ROOT_DIR)/src

TARGET = AxiSTransportLayer
VLOGDIR = verilog
TEST_FILE = Test$(TARGET).py
TOP ?= mk$(TARGET)
VLOG_FILE = $(VLOGDIR)/$(TOP).v

cocotb: $(VLOG_FILE) bsvsettings
	mkdir -p $(BUILDDIR)
	python3 $(TEST_FILE)

bsvsettings:
	python3 match_settings.py $(ROOT_DIR)

$(VLOG_FILE): $(SRC_DIR)/$(BUILDDIR) $(SRC_DIR)/$(VDIR)
	mkdir -p $(VLOGDIR)
	echo "" > $(VLOG_FILE)        
	bluetcl listVlogFiles.tcl -bdir $(SRC_DIR)/$(BUILDDIR) -vdir $(SRC_DIR)/$(VDIR) $(TOP) $(TOP) | grep -i '\.v' | xargs -I {} cat {} >> $(VLOG_FILE)

$(SRC_DIR)/$(BUILDDIR) $(SRC_DIR)/$(VDIR):
	make -C $(SRC_DIR)

clean:
	rm -rf $(BUILDDIR) $(VLOGDIR) __pycache__ 

.PHONY: cocotb bsvsettings
