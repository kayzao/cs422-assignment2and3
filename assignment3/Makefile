obj-m := tcp_rttgood.o
KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all clean load unload
all: ; $(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean: ; $(MAKE) -C $(KDIR) M=$(CURDIR) clean
load: ; sudo insmod ./tcp_rttgood.ko
unload: ; sudo rmmod tcp_rttgood
