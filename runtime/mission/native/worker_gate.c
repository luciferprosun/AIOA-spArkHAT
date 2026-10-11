#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
int main(int argc,char **argv) {
 if(argc<5)return 80;
 char *end=NULL;long fd=strtol(argv[1],&end,10);
 if(!end||*end||fd<3||fd>63||strcmp(argv[3],"/usr/bin/bwrap"))return 81;
 char ack=0;if(read((int)fd,&ack,1)!=1||ack!='G')return 82;
 close((int)fd);
 int cg=open("/proc/self/cgroup",O_RDONLY|O_CLOEXEC);char text[4096]={0};
 if(cg<0)return 83;
 ssize_t n=read(cg,text,sizeof(text)-1);close(cg);
 if(n<=0||n>=(ssize_t)sizeof(text)-1)return 84;
 text[n]=0;
 if(strcmp(text,argv[2]))return 85;
 execv(argv[3],argv+3);return 86;
}
