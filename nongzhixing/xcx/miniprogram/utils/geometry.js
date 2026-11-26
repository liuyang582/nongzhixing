// 近似转换供地图显示参考，不作为测绘成果。
const pi=Math.PI,a=6378245,ee=0.00669342162296594323
function wgsToGcj([lng,lat]){
 if(lng<72.004||lng>137.8347||lat<0.8293||lat>55.8271)return [lng,lat]
 const x=lng-105,y=lat-35
 let dl=-100+2*x+3*y+0.2*y*y+0.1*x*y+0.2*Math.sqrt(Math.abs(x))
 dl+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3+(20*Math.sin(y*pi)+40*Math.sin(y*pi/3))*2/3+(160*Math.sin(y*pi/12)+320*Math.sin(y*pi/30))*2/3
 let dn=300+x+2*y+0.1*x*x+0.1*x*y+0.1*Math.sqrt(Math.abs(x))
 dn+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3+(20*Math.sin(x*pi)+40*Math.sin(x*pi/3))*2/3+(150*Math.sin(x*pi/12)+300*Math.sin(x*pi/30))*2/3
 const rad=lat*pi/180,magic=1-ee*Math.sin(rad)**2,sqrt=Math.sqrt(magic)
 return [lng+dn*180/(a/sqrt*Math.cos(rad)*pi),lat+dl*180/(a*(1-ee)/(magic*sqrt)*pi)]
}

function valid(p){return Array.isArray(p)&&p.length>=2&&typeof p[0]==='number'&&typeof p[1]==='number'&&Number.isFinite(p[0])&&Number.isFinite(p[1])&&Math.abs(p[0])<=180&&Math.abs(p[1])<=90}
function point(p){const c=wgsToGcj(p);return {longitude:c[0],latitude:c[1]}}
function mapData(row){
 const data=row.data||{},g=data.geometry;let polygons=[],points=[]
 const parts=g&&g.type==='Polygon'?[g.coordinates]:g&&g.type==='MultiPolygon'?g.coordinates:[]
 if(Array.isArray(parts))for(const rings of parts){const ring=Array.isArray(rings)&&rings[0];if(!Array.isArray(ring)||ring.length<3||!ring.every(valid))continue;const ps=ring.map(point);polygons.push({points:ps,strokeWidth:2,strokeColor:'#246b47',fillColor:'#52a56a44',zIndex:1});points=points.concat(ps)}
 const pos=valid([data.longitude,data.latitude])?point([data.longitude,data.latitude]):points[0]
 return {polygons,points:points.length?points:pos?[pos]:[],markers:pos?[{iconPath:'/images/icons/home-active.png',width:28,height:28,id:row.id,latitude:pos.latitude,longitude:pos.longitude,title:row.title,callout:{content:row.title,display:'ALWAYS',padding:8,borderRadius:8}}]:[],latitude:pos?pos.latitude:0,longitude:pos?pos.longitude:0,hasLocation:!!pos}
}
module.exports={wgsToGcj,mapData}
