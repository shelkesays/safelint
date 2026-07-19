<?php

class Item extends Model
{
    protected $guarded = [];
}

class SafeItem extends Model
{
    protected $fillable = ['name', 'price'];
}
