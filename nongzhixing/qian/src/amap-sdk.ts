import {api} from './api'
export type Point=[number,number]
export interface LngLat{getLng():number;getLat():number}
export interface Overlay{on(event:string,callback:()=>void):void}
export interface Polygon extends Overlay{getPath():LngLat[]}
export interface MapView{add(overlays:Overlay|Overlay[]):void;remove(overlays:Overlay|Overlay[]):void;setFitView(overlays?:Overlay[],immediately?:boolean,padding?:number[],maxZoom?:number):void;setZoomAndCenter(zoom:number,point:Point):void;addControl(control:unknown):void;setLayers(layers:unknown[]):void;destroy():void}
export interface MouseTool{polygon(options:Record<string,unknown>):void;close(clear?:boolean):void;on(event:string,callback:(event:{obj:Polygon})=>void):void}
export interface Editor{open():void;close():void}
export interface SDK{
 Map:new(el:HTMLElement,options:Record<string,unknown>)=>MapView
 Polygon:new(options:Record<string,unknown>)=>Polygon
 Marker:new(options:Record<string,unknown>)=>Overlay
 MouseTool:new(map:MapView)=>MouseTool
 PolygonEditor:new(map:MapView,polygon:Polygon)=>Editor
 Scale:new()=>unknown
 ToolBar:new()=>unknown
 TileLayer:{new():unknown;Satellite:new()=>unknown;RoadNet:new()=>unknown}
 Geocoder:new()=>{getLocation(address:string,callback:(status:string,result:{geocodes?:{location:LngLat}[];info?:string})=>void):void}
}
declare global{interface Window{AMap?:SDK;_AMapSecurityConfig?:{serviceHost:string}}}
let loading:Promise<SDK>|undefined
export function loadAMap(){
 if(window.AMap)return Promise.resolve(window.AMap)
 if(loading)return loading
 loading=(async()=>{const config=await api<{key:string;service_host:string}>('/amap/config');window._AMapSecurityConfig={serviceHost:location.origin+config.service_host}
 return await new Promise<SDK>((resolve,reject)=>{const script=document.createElement('script');const timer=setTimeout(()=>{script.remove();reject(new Error('高德地图加载超时，请检查网络后重试'))},20000)
 script.src='https://webapi.amap.com/maps?v=2.0&key='+encodeURIComponent(config.key)+'&plugin=AMap.MouseTool,AMap.PolygonEditor,AMap.Scale,AMap.ToolBar,AMap.Geocoder'
 script.onload=()=>{clearTimeout(timer);if(window.AMap)resolve(window.AMap);else reject(new Error('高德地图未初始化，请检查 Key 授权与域名配置'))};script.onerror=()=>{clearTimeout(timer);script.remove();reject(new Error('无法加载高德地图，请检查网络'))};document.head.append(script)
 })})().catch(e=>{loading=undefined;throw e})
 return loading
}
