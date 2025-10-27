// gdbctl -- gdb control via pseudo tty

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <fcntl.h>
#include <errno.h>
#include <poll.h>
#include <pty.h>
#include <utmp.h>
#include <sys/types.h>
#include <sys/wait.h>

int opt_d;                              // 1=show debug output
int opt_e;                              // 1=echo gdb output
int opt_f;                              // 1=set line buffered output
int opt_x;                              // si repetition factor

int zpxlvl;                             // current trace level

int ptypar;                             // parent PTY fd
int ptycld;                             // child PTY fd
char name[100];                         // child PTY device name

unsigned long long sicount;             // single step count

const char *gdb = "(gdb) ";             // gdb's prompt string
const char *waitstr;                    // currently active "wait for" string
char *waitstop[8] = { NULL };           // string that shows run is done

int stopflg;                            // 1=waitstop seen
char sicmd[100];

char waitbuf[10000];                    // large buffer to scan for strings
char *waitdst = waitbuf;                // current end position

pid_t pidgdb;                           // gdb's pid
pid_t pidfin;                           // stop pid
int status;                             // gdb's final status
double tvelap;                          // start time

#ifndef _USE_ZPRT_
#define _USE_ZPRT_      1
#endif

static inline int
zprtok(int lvl)
{

    return (_USE_ZPRT_ && (opt_d >= lvl));
}

#define dbg(_lvl,_fmt...) \
    do { \
        if (zprtok(_lvl)) \
            printf(_fmt); \
    } while (0)

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

// xstrcat -- concatenate a string
char *
xstrcat(char *dst,const char *src)
{
    int chr;

    for (chr = *src++;  chr != 0;  chr = *src++)
        *dst++ = chr;

    *dst = 0;

    return dst;
}

// gdbexit -- check for gdb termination
void
gdbexit(void)
{

    // NOTE: this should _not_ happen
    do {
        if (pidgdb == 0)
            break;

        pidfin = waitpid(pidgdb,&status,WNOHANG);
        if (pidfin == 0)
            break;

        pidgdb = 0;
        printf("gdbexit: WAITPID status=%8.8X\n",status);
        exit(8);
    } while (0);
}

// gdbwaitpoll -- wait for prompt string
void
gdbwaitpoll(const char *buf)
{
    char *cp;
    char **wstr;

    do {
        gdbexit();

        if (waitstr == NULL)
            break;

        // concatenate to big buffer
        dbg(2,"BUF '%s'\n",buf);
        waitdst = xstrcat(waitdst,buf);

        // check for final termination string (e.g. "exited with")
        for (wstr = waitstop;  *wstr != NULL;  ++wstr) {
            cp = *wstr;
            dbg(2,"TRYSTOP '%s'\n",cp);
            cp = strstr(waitbuf,cp);
            if (cp != NULL) {
                stopflg = 1;
                waitstop[0] = NULL;
            }
        }

        // check for the prompt (e.g. "(gdb) ")
        cp = strstr(waitbuf,waitstr);
        if (cp == NULL)
            break;

        dbg(1,"HIT on '%s'\n",waitstr);

        // got it reset things
        waitbuf[0] = 0;
        waitdst = waitbuf;
        waitstr = NULL;
    } while (0);
}

// gdbrecv -- process input from gdb
void
gdbrecv(void)
{
    struct pollfd fds[1];
    struct pollfd *fd = &fds[0];
    int xlen;
    char buf[1000];

    fd->fd = ptypar;
    fd->events = POLLIN;

    while (1) {
        gdbexit();

#if 1
        int nfd = poll(fds,1,1);
        if (nfd <= 0) {
            if (waitstr != NULL)
                continue;
            break;
        }
#endif

        // get a chunk of data
        xlen = read(ptypar,buf,sizeof(buf) - 1);
        dbg(1,"gdbrecv: READ xlen=%d\n",xlen);

        if (xlen < 0) {
            printf("ERR: %s\n",strerror(errno));
            break;
        }

        // wait until we've drained every bit of data
        if (xlen == 0) {
            if (waitstr != NULL)
                continue;
            break;
        }

        // add EOS char
        buf[xlen] = 0;

        dbg(1,"ECHO: ");
        if (opt_e)
            fwrite(buf,1,xlen,stdout);

        // wait for our prompt
        gdbwaitpoll(buf);
    }
}

// gdbwaitfor -- set up prompt string to wait for
void
gdbwaitfor(const char *wstr,int loopflg)
{

    waitstr = wstr;
    if (waitstr != NULL)
        dbg(1,"WAITFOR: '%s'\n",waitstr);

    while ((waitstr != NULL) && loopflg && (pidgdb != 0))
        gdbrecv();
}

// gdbcmd -- send command to gdb
void
gdbcmd(const char *str,const char *wstr)
{
    int rlen = strlen(str);
    int xlen = 0;

#if 0
    printf("CMD/%d: %s",rlen,str);
#endif

    gdbwaitfor(wstr,0);

    for (;  rlen > 0;  rlen -= xlen, str += xlen) {
        gdbexit();

        xlen = write(ptypar,str,rlen);
        if (xlen <= 0)
            break;

        dbg(1,"RET: rlen=%d xlen=%d\n",rlen,xlen);
        gdbrecv();
    }

    dbg(1,"END/%d\n",xlen);
}

// gdbctl -- control gdb
void
gdbctl(int argc,char **argv)
{

    // this is the optimal number for speed
    if (opt_x < 0)
        opt_x = 100;

    if (opt_x <= 1) {
        opt_x = 1;
        sprintf(sicmd,"si\n");
    }
    else
        sprintf(sicmd,"si %d\n",opt_x);

    // create pseudo TTY
    openpty(&ptypar,&ptycld,name,NULL,NULL);

    pidgdb = fork();

    // launch gdb
    if (pidgdb == 0) {
        //sleep(1);

        login_tty(ptycld);
        close(ptypar);

        char *gargs[8];
        char **gdst = gargs;

        *gdst++ = "gdb";
        *gdst++ = "-n";
        *gdst++ = "-q";
        *gdst++ = *argv;
        *gdst = NULL;

        execvp(gargs[0],gargs);
        exit(9);
    }

    // make input from gdb non-blocking
#if 1
    int flags = fcntl(ptypar,F_GETFL,0);
    flags |= O_NONBLOCK;
    fcntl(ptypar,F_SETFL,flags);
#endif

    // wait
    char **wstr = waitstop;
    *wstr++ = "exited with code";
    *wstr++ = "Program received signal";
    *wstr++ = "Program terminated with signal";
    *wstr = NULL;

    printf("TTY: %s\n",name);
    printf("SI: %d\n",opt_x);
    printf("GDB: %d\n",pidgdb);

#if 1
    sleep(2);
#endif

    gdbwaitfor(gdb,1);

    // prevent kill or quit commands from hanging
    gdbcmd("set confirm off\n",gdb);

    // set breakpoint at earliest point
#if 1
    gdbcmd("b _start\n",gdb);
#else
    gdbcmd("b main\n",gdb);
#endif

    // skip over target program name
    --argc;
    ++argv;

    // add extra arguments
    do {
        if (argc <= 0)
            break;

        char xargs[1000];
        char *xdst = xargs;
        xdst += sprintf(xdst,"set args");

        for (int avidx = 0;  avidx < argc;  ++avidx, ++argv) {
            printf("XARGS: '%s'\n",*argv);
            xdst += sprintf(xdst," %s",*argv);
        }

        xdst += sprintf(xdst,"\n");

        gdbcmd(xargs,gdb);
    } while (0);

    // run the program -- it will stop at the breakpoint we set
    gdbcmd("run\n",gdb);

    // disable the breakpoint for speed
    gdbcmd("disable\n",gdb);

    tvelap = tvgetf();

    while (1) {
        // single step an ISA instruction
        gdbcmd(sicmd,gdb);

        // check for gdb aborting
        if (pidgdb == 0)
            break;

        // check for target program exiting
        if (stopflg)
            break;

        // advance count of ISA instructions
        sicount += opt_x;
    }

    // get elapsed time
    tvelap = tvgetf() - tvelap;

    // tell gdb to quit
    gdbcmd("quit\n",NULL);

    // wait for gdb to completely terminate
    if (pidgdb != 0) {
        pidfin = waitpid(pidgdb,&status,0);
        pidgdb = 0;
    }

    // close PTY units
    close(ptypar);
    close(ptycld);
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

        case 'x':
            cp += 2;
            opt_x = (*cp != 0) ? atoi(cp) : -1;
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

    gdbctl(argc,argv);

    // print statistics
    printf("%llu instructions -- ELAPSED: %.9f -- %.3f insts / sec\n",
        sicount,tvelap,(double) sicount / tvelap);

    return 0;
}
