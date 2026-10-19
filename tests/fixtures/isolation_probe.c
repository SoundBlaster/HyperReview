/* Native canary: exercise syscalls directly, with positive controls. */
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <sys/sysctl.h>
#include <unistd.h>
extern char **environ;
static int denied(int result) { return result == -1 && (errno == EPERM || errno == EACCES); }
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"failed: %s errno=%d\n",#x,errno); return 1; } } while (0)
static int tcp(int port) {
 int fd=socket(AF_INET,SOCK_STREAM,0); if(fd<0) return -1;
 struct sockaddr_in addr={0}; addr.sin_family=AF_INET; addr.sin_port=htons(port);
 addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
 int r=connect(fd,(void*)&addr,sizeof(addr));int e=errno;close(fd);errno=e;return r;
}
int main(int argc,char **argv) {
 if(argc==2 && !strcmp(argv[1],"--sleep-canary")) {sleep(60);return 0;}
 if(argc==3 && !strcmp(argv[1],"--read-canary")) {
  int mib[]={CTL_KERN,KERN_PROCARGS2,atoi(argv[2])};
  char bytes[65536];size_t size=sizeof(bytes);
  CHECK(sysctl(mib,3,bytes,&size,NULL,0)==0);
  const char marker[]="GH_TOKEN=synthetic-only";
  for(size_t i=0;i+sizeof(marker)<=size;i++)
   if(!memcmp(bytes+i,marker,sizeof(marker))) {puts("synthetic environment readable");return 0;}
  CHECK(0);
 }
 CHECK(argc==10);
 int cpus=0;size_t cpus_size=sizeof(cpus);
 CHECK(sysctlbyname("hw.logicalcpu",&cpus,&cpus_size,NULL,0)==0 && cpus>0);
 int mib[]={CTL_KERN,KERN_PROCARGS2,atoi(argv[9])};char args_buffer[65536];size_t args_size=sizeof(args_buffer);
 int args_result=sysctl(mib,3,args_buffer,&args_size,NULL,0);
 if(args_result==0){fputs("process arguments were readable\n",stderr);return 1;}
 CHECK(denied(args_result));
 int fd=open(argv[1],O_RDONLY);CHECK(fd>=0);close(fd);
 fd=open("inside-write",O_WRONLY|O_CREAT,0600);CHECK(fd>=0);close(fd);
 CHECK(denied(open(argv[2],O_RDONLY)));
 CHECK(denied(open(argv[2],O_WRONLY)));
 CHECK(denied(open("outside-link",O_RDONLY)));
 CHECK(denied(open(argv[3],O_WRONLY)));
 CHECK(denied(link(argv[3],"policy-hardlink")));
 CHECK(denied(link(argv[4],"auth-hardlink")));
 CHECK(denied(open(argv[4],O_WRONLY)));
 CHECK(denied(unlink(argv[8])));
 fd=open(argv[4],O_RDONLY);CHECK(fd>=0);close(fd);
 CHECK(denied(rename(argv[3],"replaced-profile")));
 CHECK(denied(rename(".isolation","replaced-policy-directory")));
 CHECK(tcp(atoi(argv[5]))==0);
 CHECK(denied(tcp(atoi(argv[6]))));
 int sock=socket(AF_UNIX,SOCK_STREAM,0);
 if(sock>=0) {
  struct sockaddr_un addr={0};addr.sun_family=AF_UNIX;
  strncpy(addr.sun_path,argv[7],sizeof(addr.sun_path)-1);
  CHECK(denied(connect(sock,(void*)&addr,sizeof(addr))));close(sock);
 } else CHECK(errno==EPERM || errno==EACCES);
 pid_t pid=fork();
 if(pid==0) _exit(91);
 if(pid>0) {waitpid(pid,NULL,0);CHECK(0);}
 CHECK(errno==EPERM || errno==EACCES);
 char *args[]={"/bin/sh","-c","exit 0",NULL};
 int spawned=posix_spawn(&pid,"/bin/sh",NULL,NULL,args,environ);
 if(spawned==0) {waitpid(pid,NULL,0);CHECK(0);}
 CHECK(spawned==EPERM || spawned==EACCES);
 puts("inside-read/write and proxy-connect allowed; outside-read/write, symlink, policy/auth-write, other TCP, Unix socket, fork and shell denied");
 return 0;
}
