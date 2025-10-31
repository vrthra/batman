#ifndef PERF_COUNT_END_H
#define PERF_COUNT_END_H

#include <unistd.h>
#include <stdio.h>
#include <sys/ioctl.h>

extern int perf_fd;
extern long long cpu_instructions_executed;

static inline void perf_count_end() {
    if (perf_fd == -1) return;
    ioctl(perf_fd, PERF_EVENT_IOC_DISABLE, 0);
    long long count = 0;
    read(perf_fd, &count, sizeof(count));
    cpu_instructions_executed = count;
    /*printf("Instructions executed: %lld\n", count);*/
    close(perf_fd);
    perf_fd = -1;
}

#endif
