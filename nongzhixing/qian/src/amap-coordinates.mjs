// 近似转换供地图显示参考，不作为测绘成果。
const pi=Math.PI,a=6378245,ee=0.00669342162296594323
export function wgsToGcj([lng,lat]){
 if(lng<72.004||lng>137.8347||lat<0.8293||lat>55.8271)return [lng,lat]
 const x=lng-105,y=lat-35
 let dl=-100+2*x+3*y+0.2*y*y+0.1*x*y+0.2*Math.sqrt(Math.abs(x))
 dl+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3+(20*Math.sin(y*pi)+40*Math.sin(y*pi/3))*2/3+(160*Math.sin(y*pi/12)+320*Math.sin(y*pi/30))*2/3
 let dn=300+x+2*y+0.1*x*x+0.1*x*y+0.1*Math.sqrt(Math.abs(x))
 dn+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3+(20*Math.sin(x*pi)+40*Math.sin(x*pi/3))*2/3+(150*Math.sin(x*pi/12)+300*Math.sin(x*pi/30))*2/3
 const rad=lat*pi/180,magic=1-ee*Math.sin(rad)**2,sqrt=Math.sqrt(magic)
 return [lng+dn*180/(a/sqrt*Math.cos(rad)*pi),lat+dl*180/(a*(1-ee)/(magic*sqrt)*pi)]
}
export function gcjToWgs(point){let result=[...point];for(let i=0;i<8;i++){const c=wgsToGcj(result);result=[result[0]+point[0]-c[0],result[1]+point[1]-c[1]]}return result}
