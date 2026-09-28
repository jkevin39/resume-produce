(() => {
  const form=document.querySelector('.prepare-evidence'), payload=form?.querySelector('[name=display_order]');
  if(!payload)return;
  const containers=[...form.querySelectorAll('[data-evidence-section], [data-order-skills]')];
  const rows=container=>[...container.children].filter(n=>n.hasAttribute('data-order-id'));
  function sync() {
    const order={experience:[],project:[],skills:[]};
    for(const container of containers){
      const items=rows(container), key=container.dataset.evidenceSection || 'skills';
      order[key]=items.map(n=>n.dataset.orderId);
      items.forEach((row,i)=>row.querySelectorAll('[data-order-move]').forEach(button=>{
        button.disabled=Number(button.dataset.orderMove)<0 ? i===0 : i===items.length-1;
      }));
    }
    payload.value=JSON.stringify(order);
  }
  form.addEventListener('click',event=>{
    const button=event.target.closest('[data-order-move]');if(!button || button.disabled)return;
    event.preventDefault();event.stopPropagation();
    const row=button.closest('[data-order-id]'), container=row.parentElement, items=rows(container), index=items.indexOf(row);
    const direction=Number(button.dataset.orderMove), other=items[index+direction];
    if(!other)return;
    if(direction<0)container.insertBefore(row,other);else container.insertBefore(other,row);
    sync();
  });
  form.addEventListener('submit',sync);
  sync();
})();
