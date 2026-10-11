#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static void check(int yes,const char *name) {
    if(!yes) { printf("{\"status\":\"HANDOFF_PROBE_FAILED\",\"check\":\"%s\",\"errno\":%d}\n",name,errno);fflush(stdout);exit(86); }
}

int main(int argc,char **argv) {
    check(argc==2 && strlen(argv[1])==32,"fixed_nonce");
    int socket_fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);
    check(socket_fd>=0,"control_socket");
    struct sockaddr_un address={.sun_family=AF_UNIX};
    memcpy(address.sun_path,"/control",9);
    check(connect(socket_fd,(struct sockaddr*)&address,sizeof(address))==0,"control_connect");
    int directory=open("/artifacts",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    check(directory>=0,"artifact_directory");
    char ancillary[CMSG_SPACE(sizeof(int))]={0};
    struct iovec vector={.iov_base=argv[1],.iov_len=32};
    struct msghdr message={.msg_iov=&vector,.msg_iovlen=1,.msg_control=ancillary,.msg_controllen=sizeof(ancillary)};
    struct cmsghdr *c=CMSG_FIRSTHDR(&message);
    c->cmsg_level=SOL_SOCKET;c->cmsg_type=SCM_RIGHTS;c->cmsg_len=CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(c),&directory,sizeof(directory));
    check(sendmsg(socket_fd,&message,MSG_NOSIGNAL)==32,"directory_handoff");
    close(directory);
    char ack=0;
    check(read(socket_fd,&ack,1)==1 && ack=='Y',"host_kernel_validation_ack");
    close(socket_fd);
    struct sock_filter instructions[512];
    int filter=open("/finalfilter",O_RDONLY|O_CLOEXEC);
    check(filter>=0,"final_filter_open");
    ssize_t count=read(filter,instructions,sizeof(instructions));
    check(count>0 && count<(ssize_t)sizeof(instructions) && count%(ssize_t)sizeof(instructions[0])==0,"final_filter_size");
    close(filter);
    struct sock_fprog program={.len=(unsigned short)(count/sizeof(instructions[0])),.filter=instructions};
    check(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)==0,"nnp");
    check(prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&program)==0,"final_filter_loaded");
    check(syscall(SYS_close_range,3U,~0U,0)==0,"close_all_extra_fds");
    errno=0;check(socket(AF_UNIX,SOCK_STREAM,0)==-1 && errno==EPERM,"final_control_socket_denied");
    for(int fd=3;fd<64;fd++) { errno=0;check(fcntl(fd,F_GETFD)==-1 && errno==EBADF,"no_control_fds"); }
    char *const fixed_argv[]={"/usr/bin/python3.12","-I","-S","-B","/inputs/recipe.py",NULL};
    char *const fixed_env[]={"PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME=/nonexistent","TMPDIR=/tmp",NULL};
    execve(fixed_argv[0],fixed_argv,fixed_env);
    check(0,"fixed_python_exec");
    return 86;
}
