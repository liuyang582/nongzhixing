import test from 'node:test'
import assert from 'node:assert/strict'
import {wgsToGcj,gcjToWgs} from '../src/amap-coordinates.mjs'
test('国内坐标转换有偏移、往返误差小于约一米且不改原值',()=>{
 for(const p of [[120.15,30.27],[116.397,39.908],[113.264,23.129]]){const saved=[...p],gcj=wgsToGcj(p),back=gcjToWgs(gcj);assert.ok(Math.abs(gcj[0]-p[0])>0.001);assert.ok(Math.abs(back[0]-p[0])<0.00001);assert.ok(Math.abs(back[1]-p[1])<0.00001);assert.deepEqual(p,saved)}
})
test('境外坐标不做偏移',()=>assert.deepEqual(wgsToGcj([-0.12,51.5]),[-0.12,51.5]))
