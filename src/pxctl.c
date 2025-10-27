// ptxctl -- control via ptrace
// https://stackoverflow.com/a/54358189
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
//#include <fcntl.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/ptrace.h>
#include <sys/user.h>

int opt_d;                              // 1=show debug output
int opt_e;                              // 1=echo progress
int opt_f;                              // 1=set line buffered output

unsigned long long sicount;             // single step count

int stopflg;                            // 1=stop seen

pid_t pidtgt;                           // gdb's pid
pid_t pidfin;                           // stop pid

int status;                             // target's final status
char statbuf[1000];                     // status buffer
int coredump;                           // 1=core dumped

int zpxlvl;                             // current trace level

int regsidx;                            // regs index
struct user_regs_struct regs[2];        // current regs

#define REGSALL(_cmd) \
    _cmd(r15) \
    _cmd(r14) \
    _cmd(r13) \
    _cmd(r12) \
    _cmd(rbp) \
    _cmd(rbx) \
    _cmd(r11) \
    _cmd(r10) \
    _cmd(r9) \
    _cmd(r8) \
    _cmd(rax) \
    _cmd(rcx) \
    _cmd(rdx) \
    _cmd(rsi) \
    _cmd(rdi) \
    _cmd(orig_rax) \
    /*_cmd(rip)*/ \
    _cmd(cs) \
    _cmd(eflags) \
    _cmd(rsp) \
    _cmd(ss) \
    _cmd(fs_base) \
    _cmd(gs_base) \
    _cmd(ds) \
    _cmd(es) \
    _cmd(fs) \
    _cmd(gs)

#define REGSDIF(_reg) \
    if (cur->_reg != prev->_reg) \
        printf("  %16.16llX " #_reg "\n",cur->_reg);

double tvelap;                          // start time

#ifndef _USE_ZPRT_
#define _USE_ZPRT_      1
#endif

static inline int
zprtok(int lvl)
{

    return (_USE_ZPRT_ && (opt_d >= lvl));
}

/* #define dbg(_lvl,_fmt...) \
    do { \
        if (zprtok(_lvl)) \
            printf(_fmt); \
    } while (0)*/

#define dbg(_lvl,_fmt...) do {} while (0)

// tvgetf -- get high precision time
double
tvgetf(void)
{
    struct timespec ts;
    double sec;

    clock_gettime(CLOCK_REALTIME,&ts);
    sec = ts.tv_nsec;
    sec /= 1e9;
    sec += ts.tv_sec;

    return sec;
}

// ptxstatus -- decode status
char *
ptxstatus(int status)
{
    int zflg;
    int signo;
    char *bp;

    bp = statbuf;
    *bp = 0;

    // NOTE: do _not_ use zprtok here -- we need to force this on final
    zflg = (opt_d >= zpxlvl);

    do {
        if (zflg)
            bp += sprintf(bp,"%8.8X",status);

        if (WIFSTOPPED(status)) {
            signo = WSTOPSIG(status);
            if (zflg)
                bp += sprintf(bp," WIFSTOPPED signo=%d",signo);

            switch (signo) {
            case SIGTRAP:
                break;
            default:
                stopflg = 1;
                break;
            }
        }

        if (WIFEXITED(status)) {
            if (zflg)
                bp += sprintf(bp," WIFEXITED code=%d",WEXITSTATUS(status));
            stopflg = 1;
        }

        if (WIFSIGNALED(status)) {
            signo = WTERMSIG(status);
            if (zflg)
                bp += sprintf(bp," WIFSIGNALED signo=%d",signo);

            if (WCOREDUMP(status)) {
                coredump = 1;
                stopflg = 1;
                if (zflg)
                    bp += sprintf(bp," -- core dumped");
            }
        }
    } while (0);

    return statbuf;
}

// ptxcmd -- issue ptrace command
long
ptxcmd(enum __ptrace_request cmd,void *addr,void *data)
{
    long ret;

    dbg(zpxlvl,"ptxcmd: ENTER cmd=%d addr=%p data=%p\n",cmd,addr,data);
    ret = ptrace(cmd,pidtgt,addr,data);
    dbg(zpxlvl,"ptxcmd: EXIT ret=%ld\n",ret);

    return ret;
}

// ptxwait -- wait for target to be stopped
void
ptxwait(const char *reason)
{

    dbg(zpxlvl,"ptxwait: %s pidtgt=%d\n",reason,pidtgt);
    pidfin = waitpid(pidtgt,&status,0);

    // NOTE: we need this to decide on stop status
    ptxstatus(status);

    dbg(zpxlvl,"ptxwait: %s status=(%s) pidfin=%d\n",
        reason,statbuf,pidfin);
}

// ptxwhere -- show where we are
void
ptxwhere(int initflg)
{
    struct user_regs_struct *cur;
    struct user_regs_struct *prev;

    do {
        prev = &regs[regsidx];

        if (initflg) {
            ptxcmd(PTRACE_GETREGS,NULL,prev);
            break;
        }

        regsidx = ! regsidx;
        cur = &regs[regsidx];

        ptxcmd(PTRACE_GETREGS,NULL,cur);
        //X printf("RIP: %16.16llX (%llu)\n",cur->rip,sicount);

        if (opt_e < 2)
            break;

        REGSALL(REGSDIF);
    } while (0);
}

// ptxctl -- control ptrace
int ptxctl(int argc,char **argv) {

    pidtgt = fork();

    // launch target program
    if (pidtgt == 0) {
        pidtgt = getpid();
        ptxcmd(PTRACE_TRACEME,NULL,NULL);
        execvp(argv[0],argv);
        exit(9);
    }

#if 0
    sleep(1);
#endif

    zpxlvl = 1;

#if 0
    ptxwait("SETUP");
#endif

    // attach to tracee
    // NOTE: we do _not_ need to do this because child has done TRACEME
#if 0
    dbg(zpxlvl,"ptxctl: PREATTACH\n");
    ptxcmd(PTRACE_ATTACH,NULL,NULL);
    dbg(zpxlvl,"ptxctl: POSTATTACH\n");
#endif

    // wait for initial stop
#if 1
    ptxwait("INIT");
#endif

    if (opt_e)
        ptxwhere(1);

    dbg(zpxlvl,"ptxctl: START\n");

    tvelap = tvgetf();

    zpxlvl = 2;

    while (1) {
        dbg(zpxlvl,"ptxctl: SINGLESTEP\n");
        ptxcmd(PTRACE_SINGLESTEP,NULL,NULL);
        ptxwait("WAIT");

        sicount += 1;

        // show where we are
        if (opt_e)
            ptxwhere(0);

        dbg(zpxlvl,"ptxctl: STEPCOUNT sicount=%lld\n",sicount);

        // stop when target terminates
        if (stopflg)
            break;
    }

    zpxlvl = 0;
    ptxstatus(status);
    //X printf("ptxctl: STATUS (%s) pidfin=%d\n",statbuf,pidfin);

    // get elapsed time
    tvelap = tvgetf() - tvelap;

    /* Compute return code form final status */
    if (WIFEXITED(status)) {
      return WEXITSTATUS(status);
    } else if (WIFSIGNALED(status)) {
      int signo = WTERMSIG(status);
      return 128 + signo;
    } else {
      /*unexpected*/
      return 128;
    }
}

// main -- main program
int
main(int argc,char **argv)
{
    char *cp;

    --argc;
    ++argv;

    for (;  argc > 0;  --argc, ++argv) {
        cp = *argv;
        if (*cp != '-')
            break;

        switch (cp[1]) {
        case 'd':
            cp += 2;
            opt_d = (*cp != 0) ? atoi(cp) : 1;
            break;

        case 'e':
            cp += 2;
            opt_e = (*cp != 0) ? atoi(cp) : 1;
            break;

        case 'f':
            cp += 2;
            opt_f = (*cp != 0) ? atoi(cp) : 1;
            break;
        }
    }

    if (argc == 0) {
        printf("specify target program\n");
        exit(1);
    }

    // set output line buffering
    switch (opt_f) {
    case 0:
        break;

    case 1:
        setlinebuf(stdout);
        break;

    default:
        setbuf(stdout,NULL);
        break;
    }

    int rc = ptxctl(argc,argv);

    // print statistics
    /*printf("%llu instructions -- ELAPSED: %.9f -- %.3f insts / sec\n",
        sicount,tvelap,(double) sicount / tvelap);*/
    fprintf(stderr, "instructions:%llu\n", sicount);

    return rc;
}
