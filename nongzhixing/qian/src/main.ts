import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'ol/ol.css'
import './style.css'
import App from './App.vue'
const router = createRouter({history:createWebHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]})
const app = createApp(App).use(router).use(ElementPlus,{locale:zhCn})
// Ensure direct links are resolved before App checks login and public routes.
router.isReady().then(() => app.mount('#app'))
