import React, { memo, useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';

const EChartsChart = memo(({ content }) => {
  const chartRef = useRef(null);
  const [chartJson, setChartJson] = useState({});

  useEffect(() => {
    const data = JSON.parse(content);
    setChartJson(data);
  }, [content]);

  useEffect(() => {
    let chartInstance = null;

    if (chartRef.current) {
      chartInstance = echarts.init(chartRef.current); // del 'wonderland'
      if ('color' in chartJson) delete chartJson['color'];
      if ('series' in chartJson) {
        for (let i = 0; i < chartJson['series'].length; ++i) {
          if ('lineStyle' in chartJson['series'][i]) {
            delete chartJson['series'][i]['lineStyle'];
          }
        }
      }
      chartInstance.setOption(chartJson);
    }
    window.addEventListener('resize', handleResize);
    return () => {
      if (chartInstance) {
        chartInstance.dispose();
      }
      window.removeEventListener('resize', handleResize);
    };
  }, [chartJson]);

  const handleResize = () => {
    if (chartRef.current) {
      const chartInstance = echarts.getInstanceByDom(chartRef.current);
      if (chartInstance) {
        chartInstance.resize();
      }
    }
  };

  return <div ref={chartRef} className="w-full h-[500px]" />;
});

export default EChartsChart;