<?php

class ItemController extends Controller
{
    public function store($request)
    {
        return Item::create($request->all());
    }

    public function storeValidated($request)
    {
        $request->validate([]);
        return Item::create($request->all());
    }
}
